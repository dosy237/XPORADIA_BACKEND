import datetime
import secrets

from django.http import Http404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import SchoolClass, Subject
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import DirectorProfile, UserRole

from apps.payments.models import MobileOperator, PaymentType
from apps.payments.services import confirm_payment_completed, initiate_payment

from .constants import RETAKE_FEE_RATIO, RETAKE_MIN_SCORE, RETAKE_MIN_WAIT_DAYS, RETAKE_WINDOW_DAYS
from .models import (
    AttemptStatus,
    Certification,
    ExamAttempt,
    ExamQuestion,
    SessionEnrollment,
    TrainingModule,
    TrainingSession,
)
from .serializers import (
    AdminTrainingModuleSerializer,
    ExamAttemptResultSerializer,
    ExamQuestionSerializer,
    MyCertificationStatusSerializer,
    ONLINE_GRADABLE_TYPES,
    PublicCertificationVerificationSerializer,
    SessionEnrollmentSerializer,
    TrainingModuleSerializer,
    TrainingSessionSerializer,
)

CERTIFICATION_VALIDITY_DAYS = 730


def _affiliated_establishment_users(teacher):
    """Directeurs des établissements où cet enseignant est titulaire d'une
    classe ou enseignant dédié d'une matière — à notifier en cas de montée
    de niveau de certification (voir apps/library/views.py pour le même
    calcul d'affiliation côté bibliothèque)."""

    ids = set()
    ids.update(
        SchoolClass.objects.filter(homeroom_teacher=teacher).values_list(
            "track__department__establishment_id", flat=True
        )
    )
    ids.update(
        Subject.objects.filter(teacher=teacher).values_list(
            "school_class__track__department__establishment_id", flat=True
        )
    )
    return [profile.user for profile in DirectorProfile.objects.filter(id__in=ids).select_related("user")]


class TrainingModuleViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalogue public des modules de formation (lecture seule) — accessible
    aux visiteurs non connectés (onglet Certifications du fil public)."""

    permission_classes = [permissions.AllowAny]
    serializer_class = TrainingModuleSerializer
    queryset = TrainingModule.objects.filter(is_active=True)
    # Catalogue restreint par nature (quelques dizaines de modules) : la
    # CursorPagination globale suppose un champ "created" absent de ce modèle.
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get("category")
        target_level = self.request.query_params.get("target_level")
        if category:
            qs = qs.filter(category=category)
        if target_level:
            qs = qs.filter(target_level=target_level)
        return qs


class AdminTrainingModuleViewSet(viewsets.ModelViewSet):
    """CRUD complet des modules de formation — réservé au personnel
    (is_staff), qu'il s'agisse d'un administrateur généraliste ou d'un
    formateur (voir le groupe Django "Formateurs"). Distinct du catalogue
    public en lecture seule ci-dessus : celui-ci voit TOUT (y compris les
    modules désactivés), l'autre ne voit que is_active=True."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminTrainingModuleSerializer
    queryset = TrainingModule.objects.all().order_by("-created_at")
    pagination_class = None


class TrainingSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Sessions de formation à venir, filtrables par module et ville —
    accessible aux visiteurs non connectés."""

    permission_classes = [permissions.AllowAny]
    serializer_class = TrainingSessionSerializer
    pagination_class = None

    def get_queryset(self):
        qs = TrainingSession.objects.filter(
            date__gte=timezone.localdate()
        ).exclude(status="cancelled").select_related("module", "trainer")
        module_id = self.request.query_params.get("module")
        city = self.request.query_params.get("city")
        if module_id:
            qs = qs.filter(module_id=module_id)
        if city:
            qs = qs.filter(city__iexact=city)
        return qs


class PublicCertificationVerificationView(APIView):
    """Vérification publique d'une certification par son QR code — aucune
    authentification requise (CDC US-01-08) : un directeur ou un parent
    doit pouvoir vérifier l'authenticité d'un certificat sans compte
    Xporadia, en scannant simplement le code."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, qr_code):
        try:
            certification = Certification.objects.select_related("teacher", "module").get(qr_code=qr_code)
        except Certification.DoesNotExist:
            return Response(
                {"detail": "Aucune certification ne correspond à ce code."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(PublicCertificationVerificationSerializer(certification).data)


class MyCertificationStatusView(APIView):
    """Statut de certification de l'enseignant connecté : niveau atteint, prochain
    niveau visé, historique des certifications valides."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        data = MyCertificationStatusSerializer.build(request.user)
        return Response(MyCertificationStatusSerializer(data).data)


def _get_module(module_id):
    try:
        return TrainingModule.objects.get(id=module_id, is_active=True)
    except TrainingModule.DoesNotExist:
        raise Http404


class OnlineExamQuestionsView(APIView):
    """Questions QCM/Vrai-Faux d'un module, pour l'examen auto-corrigé en
    ligne — les questions ouvertes (nécessitant une correction humaine) sont
    exclues du parcours en ligne. Les corrigés ne sont jamais exposés."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, module_id):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        module = _get_module(module_id)
        questions = ExamQuestion.objects.filter(
            module=module, question_type__in=ONLINE_GRADABLE_TYPES, is_active=True
        )
        return Response(ExamQuestionSerializer(questions, many=True).data)


def _grade_and_issue_certification(user, module, questions, answers, *, is_retake=False):
    """Corrige un examen en ligne et délivre la certification si le score
    franchit le seuil — factorisé pour être identique entre une tentative
    normale et un rattrapage (même barème, même notification, même
    déclenchement de changement de niveau)."""
    correct_count = sum(
        1 for q in questions if str(answers.get(str(q.id), "")).strip().lower() == q.correct_answer.strip().lower()
    )
    score_auto = round((correct_count / len(questions)) * 100, 2)
    status_before = MyCertificationStatusSerializer.build(user)["current_level"]

    attempt = ExamAttempt.objects.create(
        teacher=user, module=module, is_online=True, is_retake=is_retake,
        answers=answers, score_auto=score_auto, submitted_at=timezone.now(),
    )
    attempt.compute_total_score()

    leveled_up = False
    new_level = None
    if score_auto >= ExamAttempt.PASSING_SCORE:
        attempt.status = AttemptStatus.PASSED
        attempt.graded_at = timezone.now()
        attempt.save(update_fields=["status", "graded_at"])

        certification = Certification.objects.create(
            teacher=user, module=module, attempt=attempt, level=module.target_level,
            points_awarded=module.points, score_total=attempt.score_total,
            qr_code=f"XPO-CERT-{user.id}-{secrets.token_hex(6).upper()}",
            expires_at=timezone.localdate() + datetime.timedelta(days=CERTIFICATION_VALIDITY_DAYS),
        )
        from .pdf import generate_and_attach_certificate

        generate_and_attach_certificate(certification)
        notify_user(
            user, NotificationType.EXAM_RESULT, title="Certification délivrée",
            body=f"Félicitations, votre niveau {module.target_level} pour « {module.title} » a été validé{' au rattrapage' if is_retake else ''}.",
        )

        status_after = MyCertificationStatusSerializer.build(user)["current_level"]
        if status_after != status_before:
            leveled_up = True
            new_level = status_after
            notify_user(
                user, NotificationType.EXAM_RESULT, title="Nouveau niveau atteint !",
                body=f"Bravo, vous avez atteint le niveau {status_after} sur Xporadia.",
            )
            for director_user in _affiliated_establishment_users(user):
                notify_user(
                    director_user, NotificationType.EXAM_RESULT, title="Un enseignant a progressé",
                    body=f"{user.get_full_name()} a atteint le niveau {status_after} sur Xporadia.",
                )
    else:
        attempt.status = AttemptStatus.FAILED
        attempt.save(update_fields=["status"])
        message = (
            f"Votre tentative pour « {module.title} » n'a pas atteint le seuil de réussite "
            f"({ExamAttempt.PASSING_SCORE}%)."
        )
        if not is_retake and score_auto >= RETAKE_MIN_SCORE:
            message += " Vous êtes éligible à une session de rattrapage."
        notify_user(user, NotificationType.EXAM_RESULT, title="Résultat d'examen", body=message)

    attempt.leveled_up = leveled_up
    attempt.new_level = new_level
    return attempt


class SubmitOnlineExamView(APIView):
    """Soumission des réponses à l'examen en ligne d'un module : correction
    automatique, et si le score franchit le seuil de réussite, délivrance
    immédiate de la certification (sans intervention d'un formateur)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, module_id):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        module = _get_module(module_id)
        answers = request.data.get("answers")
        if not isinstance(answers, dict) or not answers:
            return Response({"detail": "Réponses manquantes."}, status=status.HTTP_400_BAD_REQUEST)

        questions = list(
            ExamQuestion.objects.filter(
                module=module, question_type__in=ONLINE_GRADABLE_TYPES, is_active=True
            )
        )
        if not questions:
            return Response(
                {"detail": "Ce module n'a pas d'examen en ligne disponible."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attempt = _grade_and_issue_certification(request.user, module, questions, answers)
        return Response(ExamAttemptResultSerializer(attempt).data, status=status.HTTP_201_CREATED)


def _retake_eligibility(user, module):
    """Renvoie (éligible: bool, motif si non éligible, tentative échouée
    concernée) — logique centrale du rattrapage, réutilisée par les deux
    vues ci-dessous pour ne jamais désynchroniser la vérification et
    l'action."""
    if Certification.objects.filter(teacher=user, module=module, is_valid=True).exists():
        return False, "Vous êtes déjà certifié(e) sur ce module.", None

    if ExamAttempt.objects.filter(teacher=user, module=module, is_retake=True).exists():
        return False, "Le rattrapage de ce module a déjà été utilisé.", None

    failed_attempt = (
        ExamAttempt.objects.filter(
            teacher=user, module=module, is_online=True, is_retake=False, status=AttemptStatus.FAILED,
        )
        .order_by("-submitted_at")
        .first()
    )
    if not failed_attempt or failed_attempt.score_auto is None or failed_attempt.submitted_at is None:
        return False, "Aucune tentative échouée éligible pour ce module.", None
    if failed_attempt.score_auto < RETAKE_MIN_SCORE:
        return False, "Le score obtenu est trop bas pour un rattrapage — il faut reprendre le module.", None

    days_since_fail = (timezone.now() - failed_attempt.submitted_at).days
    if days_since_fail < RETAKE_MIN_WAIT_DAYS:
        return False, f"Le rattrapage n'est ouvert qu'à partir de {RETAKE_MIN_WAIT_DAYS} jours après l'échec.", None
    if days_since_fail > RETAKE_WINDOW_DAYS:
        return False, "La fenêtre de rattrapage (30 jours) est dépassée.", None

    return True, None, failed_attempt


class RetakeEligibilityView(APIView):
    """Vérifie si l'enseignant peut passer un rattrapage sur ce module —
    alimente l'écran avant même de tenter le paiement."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, module_id):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        module = _get_module(module_id)
        eligible, reason, failed_attempt = _retake_eligibility(request.user, module)
        return Response({
            "eligible": eligible,
            "reason": reason,
            "fee": round(module.price * RETAKE_FEE_RATIO) if eligible else None,
            "previous_score": failed_attempt.score_auto if failed_attempt else None,
        })


class RetakeExamView(APIView):
    """Rattrapage — paiement réduit (50% du tarif du module) puis
    soumission d'un nouvel examen, une seule fois par module."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, module_id):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        module = _get_module(module_id)
        eligible, reason, _ = _retake_eligibility(request.user, module)
        if not eligible:
            return Response({"detail": reason}, status=status.HTTP_400_BAD_REQUEST)

        answers = request.data.get("answers")
        if not isinstance(answers, dict) or not answers:
            return Response({"detail": "Réponses manquantes."}, status=status.HTTP_400_BAD_REQUEST)

        operator = request.data.get("operator")
        phone_number = request.data.get("phone_number")
        if operator not in MobileOperator.values or not phone_number:
            return Response(
                {"detail": "Opérateur Mobile Money et numéro de téléphone requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        questions = list(
            ExamQuestion.objects.filter(
                module=module, question_type__in=ONLINE_GRADABLE_TYPES, is_active=True
            )
        )
        if not questions:
            return Response(
                {"detail": "Ce module n'a pas d'examen en ligne disponible."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fee = round(module.price * RETAKE_FEE_RATIO)
        payment = initiate_payment(
            user=request.user, amount=fee, operator=operator, phone_number=phone_number,
            payment_type=PaymentType.TRAINING,
        )
        confirm_payment_completed(payment)

        attempt = _grade_and_issue_certification(request.user, module, questions, answers, is_retake=True)
        return Response(ExamAttemptResultSerializer(attempt).data, status=status.HTTP_201_CREATED)


def _get_session(session_id):
    try:
        return TrainingSession.objects.select_related("module", "trainer").get(id=session_id)
    except TrainingSession.DoesNotExist:
        raise Http404


class EnrollInSessionView(APIView):
    """Inscription (et paiement Mobile Money immédiat) d'un enseignant à une
    session de formation en présentiel — le paiement va directement à
    Xporadia (pas de séquestre : il n'y a pas de contrepartie à libérer,
    contrairement aux cours particuliers)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        session = _get_session(session_id)

        if session.is_full:
            return Response({"detail": "Cette session est complète."}, status=status.HTTP_400_BAD_REQUEST)
        if SessionEnrollment.objects.filter(session=session, teacher=request.user).exists():
            return Response(
                {"detail": "Vous êtes déjà inscrit(e) à cette session."}, status=status.HTTP_400_BAD_REQUEST
            )

        operator = request.data.get("operator")
        phone_number = request.data.get("phone_number")
        if operator not in MobileOperator.values or not phone_number:
            return Response(
                {"detail": "Opérateur Mobile Money et numéro de téléphone requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment = initiate_payment(
            user=request.user, amount=session.module.price, operator=operator, phone_number=phone_number,
            payment_type=PaymentType.TRAINING,
        )
        confirm_payment_completed(payment)

        enrollment = SessionEnrollment.objects.create(
            session=session, teacher=request.user, payment_status="paid", payment=payment
        )
        session.enrolled_count += 1
        session.save(update_fields=["enrolled_count"])

        notify_user(
            request.user,
            NotificationType.SESSION_CONFIRMED,
            title="Inscription confirmée",
            body=f"Votre inscription à « {session.module.title} » ({session.city}, {session.date}) est confirmée.",
        )
        notify_user(
            session.trainer,
            NotificationType.SESSION_CONFIRMED,
            title="Nouvelle inscription",
            body=f"{request.user.get_full_name()} s'est inscrit(e) à votre session « {session.module.title} ».",
        )

        return Response(SessionEnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)


class MySessionEnrollmentsView(APIView):
    """Suivi, côté enseignant, des inscriptions aux sessions de formation."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        enrollments = (
            SessionEnrollment.objects.filter(teacher=request.user)
            .select_related("session__module", "session__trainer", "payment")
            .order_by("-enrolled_at")
        )
        return Response(SessionEnrollmentSerializer(enrollments, many=True).data)
