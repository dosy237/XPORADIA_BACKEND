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

from .models import AttemptStatus, Certification, ExamAttempt, ExamQuestion, TrainingModule, TrainingSession
from .serializers import (
    ExamAttemptResultSerializer,
    ExamQuestionSerializer,
    MyCertificationStatusSerializer,
    ONLINE_GRADABLE_TYPES,
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

        correct_count = sum(
            1 for q in questions if str(answers.get(str(q.id), "")).strip().lower() == q.correct_answer.strip().lower()
        )
        score_auto = round((correct_count / len(questions)) * 100, 2)

        status_before = MyCertificationStatusSerializer.build(request.user)["current_level"]

        attempt = ExamAttempt.objects.create(
            teacher=request.user,
            module=module,
            is_online=True,
            answers=answers,
            score_auto=score_auto,
            submitted_at=timezone.now(),
        )
        attempt.compute_total_score()

        leveled_up = False
        new_level = None
        if score_auto >= ExamAttempt.PASSING_SCORE:
            attempt.status = AttemptStatus.PASSED
            attempt.graded_at = timezone.now()
            attempt.save(update_fields=["status", "graded_at"])

            Certification.objects.create(
                teacher=request.user,
                module=module,
                attempt=attempt,
                level=module.target_level,
                score_total=attempt.score_total,
                qr_code=f"XPO-CERT-{request.user.id}-{secrets.token_hex(6).upper()}",
                expires_at=timezone.localdate() + datetime.timedelta(days=CERTIFICATION_VALIDITY_DAYS),
            )
            notify_user(
                request.user,
                NotificationType.EXAM_RESULT,
                title="Certification délivrée",
                body=f"Félicitations, votre niveau {module.target_level} pour « {module.title} » a été validé automatiquement.",
            )

            status_after = MyCertificationStatusSerializer.build(request.user)["current_level"]
            if status_after != status_before:
                leveled_up = True
                new_level = status_after
                notify_user(
                    request.user,
                    NotificationType.EXAM_RESULT,
                    title="Nouveau niveau atteint !",
                    body=f"Bravo, vous avez atteint le niveau {status_after} sur Xporadia.",
                )
                for director_user in _affiliated_establishment_users(request.user):
                    notify_user(
                        director_user,
                        NotificationType.EXAM_RESULT,
                        title="Un enseignant a progressé",
                        body=f"{request.user.get_full_name()} a atteint le niveau {status_after} sur Xporadia.",
                    )
        else:
            attempt.status = AttemptStatus.FAILED
            attempt.save(update_fields=["status"])
            notify_user(
                request.user,
                NotificationType.EXAM_RESULT,
                title="Résultat d'examen",
                body=f"Votre tentative pour « {module.title} » n'a pas atteint le seuil de réussite ({ExamAttempt.PASSING_SCORE}%).",
            )

        attempt.leveled_up = leveled_up
        attempt.new_level = new_level
        return Response(ExamAttemptResultSerializer(attempt).data, status=status.HTTP_201_CREATED)
