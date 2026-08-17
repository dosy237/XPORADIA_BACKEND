from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Child, Enrollment, EnrollmentStatus, SchoolClass, Subject
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import UserRole

from . import services
from .models import (
    Evaluation,
    Grade,
    JoinRequestStatus,
    EstablishmentJoinRequest,
    ReportCard,
    SubjectReportEntry,
    Term,
)
from .serializers import (
    BulkGradeEntrySerializer,
    EvaluationSerializer,
    GradeSerializer,
    JoinRequestSerializer,
    ReportCardSerializer,
    TermSerializer,
)


def _require_director_establishment(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux établissements.")
    from apps.users.models import DirectorProfile

    try:
        return user.director_profile
    except DirectorProfile.DoesNotExist:
        raise PermissionDenied("Aucun établissement associé à ce compte.")


def _require_subject_teacher(subject, user):
    """Seul l'enseignant dédié de CETTE matière peut y créer des
    évaluations et y saisir des notes — jamais le titulaire de la classe
    à sa place (sauf s'il est lui-même l'enseignant dédié de la matière),
    cohérent avec \"chaque enseignant saisit pour sa propre matière\"."""
    if subject.teacher_id != user.id:
        raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")


class TermListCreateView(generics.ListCreateAPIView):
    """Trimestres de l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TermSerializer
    pagination_class = None

    def get_queryset(self):
        establishment = _require_director_establishment(self.request.user)
        return Term.objects.filter(establishment=establishment)

    def perform_create(self, serializer):
        establishment = _require_director_establishment(self.request.user)
        serializer.save(establishment=establishment)


class TermDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TermSerializer

    def get_queryset(self):
        establishment = _require_director_establishment(self.request.user)
        return Term.objects.filter(establishment=establishment)


class MyActiveTermView(APIView):
    """Trimestre en cours de l'établissement d'une classe donnée —
    alimente les écrans de saisie enseignant sans qu'ils aient à choisir
    manuellement le bon trimestre à chaque fois."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, class_id):
        try:
            school_class = SchoolClass.objects.select_related(
                "track__department__establishment"
            ).get(id=class_id)
        except SchoolClass.DoesNotExist:
            raise Http404
        establishment = school_class.track.department.establishment
        term = Term.objects.filter(establishment=establishment, is_active=True).first()
        if not term:
            return Response({"detail": "Aucun trimestre actif pour cet établissement."}, status=404)
        return Response(TermSerializer(term).data)


class EvaluationListCreateView(generics.ListCreateAPIView):
    """Évaluations d'une matière — créées et consultées par son enseignant
    dédié uniquement."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EvaluationSerializer
    pagination_class = None

    def get_subject(self):
        subject = get_object_or_404(Subject, pk=self.kwargs["subject_id"])
        _require_subject_teacher(subject, self.request.user)
        return subject

    def get_queryset(self):
        return Evaluation.objects.filter(subject=self.get_subject()).select_related("subject")

    def perform_create(self, serializer):
        serializer.save(subject=self.get_subject(), created_by=self.request.user)


class EvaluationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EvaluationSerializer

    def get_queryset(self):
        return Evaluation.objects.select_related("subject")

    def get_object(self):
        evaluation = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        _require_subject_teacher(evaluation.subject, self.request.user)
        return evaluation


class EvaluationGradesView(APIView):
    """Saisie en lot des notes d'une évaluation — GET renvoie tout
    l'effectif de la classe avec la note existante si déjà saisie (jamais
    besoin de redemander la liste séparément), POST enregistre tout le
    lot en une seule requête plutôt qu'un appel par élève."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_evaluation(self, evaluation_id, user):
        evaluation = get_object_or_404(Evaluation.objects.select_related("subject"), pk=evaluation_id)
        _require_subject_teacher(evaluation.subject, user)
        return evaluation

    def get(self, request, evaluation_id):
        evaluation = self._get_evaluation(evaluation_id, request.user)
        enrollments = Enrollment.objects.filter(
            school_class=evaluation.subject.school_class, status=EnrollmentStatus.ACTIVE
        ).select_related("child")
        existing_grades = {
            g.child_id: g for g in Grade.objects.filter(evaluation=evaluation)
        }
        roster = []
        for enrollment in enrollments:
            grade = existing_grades.get(enrollment.child_id)
            roster.append({
                "child": enrollment.child.id,
                "child_first_name": enrollment.child.first_name,
                "child_last_name": enrollment.child.last_name,
                "score": grade.score if grade else None,
                "is_excused": grade.is_excused if grade else False,
            })
        return Response(roster)

    def post(self, request, evaluation_id):
        evaluation = self._get_evaluation(evaluation_id, request.user)
        entries = request.data if isinstance(request.data, list) else request.data.get("entries", [])
        serializer = BulkGradeEntrySerializer(data=entries, many=True)
        serializer.is_valid(raise_exception=True)

        valid_child_ids = set(
            Enrollment.objects.filter(
                school_class=evaluation.subject.school_class, status=EnrollmentStatus.ACTIVE
            ).values_list("child_id", flat=True)
        )
        saved = []
        for entry in serializer.validated_data:
            if entry["child"] not in valid_child_ids:
                continue  # élève qui n'est plus inscrit dans cette classe — ignoré, pas d'erreur bloquante
            grade, _ = Grade.objects.update_or_create(
                evaluation=evaluation, child_id=entry["child"],
                defaults={"score": entry.get("score"), "is_excused": entry.get("is_excused", False)},
            )
            saved.append(grade)
        return Response(GradeSerializer(saved, many=True).data)


class ClassReportPreviewView(APIView):
    """Aperçu des moyennes calculées AVANT publication — pour que le
    directeur (ou le titulaire) vérifie que tout est cohérent avant de
    déclencher la génération définitive des bulletins. Rien n'est écrit
    en base ici, uniquement du calcul à la volée."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, class_id, term_id):
        school_class = get_object_or_404(
            SchoolClass.objects.select_related("track__department__establishment"), pk=class_id
        )
        term = get_object_or_404(Term, pk=term_id)
        user = request.user
        is_director = (
            user.has_role(UserRole.DIRECTOR)
            and school_class.track.department.establishment.user_id == user.id
        )
        is_homeroom = school_class.homeroom_teacher_id == user.id
        if not (is_director or is_homeroom):
            raise PermissionDenied("Réservé au directeur ou au titulaire de cette classe.")

        result = services.compute_class_rankings(school_class, term)
        return Response({
            "class_average": result["class_average"],
            "ranked": [
                {
                    "child": e["child"].id, "first_name": e["child"].first_name,
                    "last_name": e["child"].last_name, "general_average": e["general_average"],
                    "rank": e["rank"],
                }
                for e in result["ranked"]
            ],
            "without_average": [
                {"child": c.id, "first_name": c.first_name, "last_name": c.last_name}
                for c in result["without_average"]
            ],
        })


class GenerateReportCardsView(APIView):
    """Génération ET publication des bulletins de TOUTE une classe pour un
    trimestre, en un seul geste — jamais élève par élève. Réservée au
    directeur (contrôle éditorial avant que les familles voient quoi que
    ce soit). Republier écrase le bulletin précédent du même trimestre
    (utile si une erreur de note est corrigée après une 1re publication)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, class_id, term_id):
        school_class = get_object_or_404(
            SchoolClass.objects.select_related("track__department__establishment"), pk=class_id
        )
        term = get_object_or_404(Term, pk=term_id)
        if school_class.track.department.establishment.user_id != request.user.id:
            raise PermissionDenied("Cette classe n'appartient pas à votre établissement.")

        homeroom_comments = request.data.get("homeroom_comments", {})  # {child_id: "commentaire"}
        result = services.compute_class_rankings(school_class, term)
        subjects = list(Subject.objects.filter(school_class=school_class))

        created_or_updated = []
        for entry in result["ranked"]:
            child = entry["child"]
            report_card, _ = ReportCard.objects.update_or_create(
                child=child, term=term,
                defaults={
                    "school_class": school_class,
                    "general_average": entry["general_average"],
                    "class_average": result["class_average"],
                    "rank": entry["rank"],
                    "class_size": entry["class_size"],
                    "homeroom_comment": homeroom_comments.get(str(child.id), ""),
                },
            )
            report_card.subject_entries.all().delete()
            for subject in subjects:
                subject_avg = services.compute_subject_average(child, subject, term)
                SubjectReportEntry.objects.create(
                    report_card=report_card, subject_name=subject.name,
                    subject_average=subject_avg, coefficient=subject.coefficient,
                )

            from .pdf import generate_and_attach_report_card

            generate_and_attach_report_card(report_card)
            created_or_updated.append(report_card)

            if child.user_id:
                notify_user(
                    child.user, NotificationType.REPORT_CARD_PUBLISHED,
                    title="Bulletin disponible",
                    body=f"Votre bulletin du {term} est disponible — moyenne générale : {entry['general_average']}/20.",
                )
            if child.parent and child.parent.user_id:
                notify_user(
                    child.parent.user, NotificationType.REPORT_CARD_PUBLISHED,
                    title="Bulletin disponible",
                    body=f"Le bulletin de {child.first_name} pour le {term} est disponible.",
                )

        return Response(
            ReportCardSerializer(created_or_updated, many=True).data, status=status.HTTP_201_CREATED
        )


class MyReportCardsView(generics.ListAPIView):
    """Bulletins publiés de l'élève connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportCardSerializer
    pagination_class = None

    def get_queryset(self):
        child = getattr(self.request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        return ReportCard.objects.filter(child=child).prefetch_related("subject_entries")


class ChildReportCardsView(generics.ListAPIView):
    """Bulletins publiés d'un enfant, consultés par son parent."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportCardSerializer
    pagination_class = None

    def get_queryset(self):
        child = get_object_or_404(Child, pk=self.kwargs["child_id"])
        if not child.parent_id or child.parent.user_id != self.request.user.id:
            raise PermissionDenied("Cet élève n'est pas rattaché à votre compte.")
        return ReportCard.objects.filter(child=child).prefetch_related("subject_entries")


class JoinRequestCreateView(APIView):
    """Soumission d'une demande de rattachement à un établissement —
    utilisée juste après l'inscription (flux normal) ou plus tard depuis
    l'écran "Rejoindre mon établissement" (option "plus tard" honorée).
    Jamais une inscription automatique : crée une demande PENDING, le
    directeur valide ensuite."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        if EstablishmentJoinRequest.objects.filter(child=child, status=JoinRequestStatus.PENDING).exists():
            return Response(
                {"detail": "Une demande est déjà en attente pour ce compte."}, status=status.HTTP_400_BAD_REQUEST
            )

        establishment_id = request.data.get("establishment")
        other_name = (request.data.get("other_establishment_name") or "").strip()
        declared_level = request.data.get("declared_level", child.class_level)

        if not establishment_id and not other_name:
            raise ValidationError({"establishment": "Précisez un établissement, ou son nom si absent de la liste."})

        establishment = None
        if establishment_id:
            from apps.users.models import DirectorProfile

            # La recherche d'établissement (EstablishmentDirectoryCardSerializer)
            # renvoie l'ID UTILISATEUR, pas DirectorProfile.pk (distincts,
            # DirectorProfile.user n'est pas la clé primaire) — cohérent
            # avec la route publique /auth/establishments/<user_id>/.
            establishment = get_object_or_404(DirectorProfile, user_id=establishment_id)

        join_request = EstablishmentJoinRequest.objects.create(
            child=child, establishment=establishment,
            other_establishment_name="" if establishment else other_name,
            declared_level=declared_level,
        )

        if establishment:
            notify_user(
                establishment.user, NotificationType.ENROLLMENT_UPDATE,
                title="Nouvelle demande de rattachement",
                body=f"{child.first_name} {child.last_name} demande à rejoindre votre établissement.",
                data={"join_request_id": join_request.id},
            )

        return Response(JoinRequestSerializer(join_request).data, status=status.HTTP_201_CREATED)


class MyJoinRequestView(APIView):
    """Statut de la demande de rattachement de l'élève connecté."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        join_request = EstablishmentJoinRequest.objects.filter(child=child).order_by("-created_at").first()
        return Response({
            "join_request": JoinRequestSerializer(join_request).data if join_request else None,
        })


class DirectorJoinRequestsView(generics.ListAPIView):
    """Demandes de rattachement en attente pour l'établissement du
    directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JoinRequestSerializer
    pagination_class = None

    def get_queryset(self):
        establishment = _require_director_establishment(self.request.user)
        return EstablishmentJoinRequest.objects.filter(
            establishment=establishment
        ).select_related("child").order_by("status", "-created_at")


class ReviewJoinRequestView(APIView):
    """Le directeur valide ou rejette une demande — jamais d'écriture
    automatique en base avant ce geste humain. L'approbation peut inclure
    directement le placement en classe (class_id) : un seul geste plutôt
    que deux allers-retours, essentiel quand l'effectif est important."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        establishment = _require_director_establishment(request.user)
        join_request = get_object_or_404(
            EstablishmentJoinRequest.objects.select_related("child__user"), pk=pk, establishment=establishment
        )
        if join_request.status != JoinRequestStatus.PENDING:
            return Response({"detail": "Cette demande a déjà été traitée."}, status=status.HTTP_400_BAD_REQUEST)

        approve = request.data.get("approve", True)
        join_request.status = JoinRequestStatus.APPROVED if approve else JoinRequestStatus.REJECTED
        join_request.rejection_reason = request.data.get("rejection_reason", "") if not approve else ""
        join_request.reviewed_at = timezone.now()
        join_request.save(update_fields=["status", "rejection_reason", "reviewed_at"])

        enrollment_created = False
        class_id = request.data.get("class_id")
        if approve and class_id:
            from apps.academics.models import Enrollment, EnrollmentStatus, SchoolClass

            school_class = get_object_or_404(
                SchoolClass.objects.select_related("track__department__establishment"), pk=class_id
            )
            if school_class.track.department.establishment_id != establishment.id:
                raise ValidationError({"class_id": "Cette classe n'appartient pas à votre établissement."})
            _, enrollment_created = Enrollment.objects.get_or_create(
                child=join_request.child, school_class=school_class,
                defaults={"status": EnrollmentStatus.ACTIVE},
            )

        if join_request.child.user_id:
            body = (
                f"{establishment.school_name} a approuvé votre rattachement."
                if approve
                else f"{establishment.school_name} a refusé votre rattachement"
                f"{' : ' + join_request.rejection_reason if join_request.rejection_reason else '.'}"
            )
            if enrollment_created:
                body += f" Vous êtes inscrit(e) en {school_class}."
            notify_user(
                join_request.child.user, NotificationType.ENROLLMENT_UPDATE,
                title="Rattachement " + ("approuvé" if approve else "refusé"),
                body=body,
            )
        return Response(JoinRequestSerializer(join_request).data)


class ApprovedUnplacedChildrenView(generics.ListAPIView):
    """Élèves dont la demande de rattachement a été approuvée mais qui ne
    sont encore inscrits dans aucune classe — le pont naturel entre
    l'admission et l'affectation à une classe, pour éviter au directeur
    de rechercher un par un les élèves auto-inscrits (Child.parent nul,
    donc introuvables par email de parent)."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        establishment = _require_director_establishment(request.user)
        approved = EstablishmentJoinRequest.objects.filter(
            establishment=establishment, status=JoinRequestStatus.APPROVED
        ).select_related("child")

        unplaced = []
        for join_request in approved:
            has_active_enrollment = Enrollment.objects.filter(
                child=join_request.child, status=EnrollmentStatus.ACTIVE
            ).exists()
            if not has_active_enrollment:
                unplaced.append({
                    "child": join_request.child.id,
                    "first_name": join_request.child.first_name,
                    "last_name": join_request.child.last_name,
                    "declared_level": join_request.declared_level,
                    "approved_at": join_request.reviewed_at,
                })
        return Response(unplaced)


class ParseAdmissionReportView(APIView):
    """Dépôt d'un rapport d'admission (CSV ou PDF) — parse le fichier et
    propose un rapprochement avec les demandes de rattachement en
    attente. Rien n'est écrit en base ici : c'est une proposition à
    relire, voir ConfirmAdmissionReportView pour l'application réelle."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        establishment = _require_director_establishment(request.user)
        uploaded = request.FILES.get("file")
        if not uploaded:
            raise ValidationError({"file": "Un fichier est requis."})

        from . import admission_report

        filename = (uploaded.name or "").lower()
        if filename.endswith(".csv"):
            try:
                extracted = admission_report.parse_csv_report(uploaded)
            except Exception:
                raise ValidationError({"file": "Fichier CSV illisible — vérifiez l'encodage et les colonnes."})
        elif filename.endswith(".pdf"):
            try:
                extracted = admission_report.parse_pdf_report(uploaded)
            except Exception:
                raise ValidationError({"file": "Fichier PDF illisible."})
        else:
            raise ValidationError({"file": "Formats acceptés : .csv ou .pdf."})

        pending = EstablishmentJoinRequest.objects.filter(
            establishment=establishment, status=JoinRequestStatus.PENDING
        ).select_related("child")
        proposals = admission_report.match_report_to_join_requests(extracted, pending)
        return Response({"total_lines": len(extracted), "proposals": proposals})


class ConfirmAdmissionReportView(APIView):
    """Application du rapprochement — après relecture du directeur.
    Traite chaque ligne indépendamment (un échec n'annule jamais les
    autres), même principe que le passage en masse."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        establishment = _require_director_establishment(request.user)
        decisions = request.data.get("decisions", [])
        if not isinstance(decisions, list) or not decisions:
            raise ValidationError({"decisions": "Au moins une décision est requise."})

        results = []
        for decision in decisions:
            join_request_id = decision.get("join_request_id")
            approve = decision.get("approve", True)
            class_id = decision.get("class_id")
            try:
                join_request = EstablishmentJoinRequest.objects.select_related("child__user").get(
                    pk=join_request_id, establishment=establishment, status=JoinRequestStatus.PENDING
                )
                join_request.status = JoinRequestStatus.APPROVED if approve else JoinRequestStatus.REJECTED
                join_request.reviewed_at = timezone.now()
                join_request.save(update_fields=["status", "reviewed_at"])

                if approve and class_id:
                    from apps.academics.models import Enrollment, EnrollmentStatus, SchoolClass

                    school_class = SchoolClass.objects.select_related(
                        "track__department__establishment"
                    ).get(pk=class_id)
                    if school_class.track.department.establishment_id != establishment.id:
                        raise ValueError("Classe hors établissement.")
                    Enrollment.objects.get_or_create(
                        child=join_request.child, school_class=school_class,
                        defaults={"status": EnrollmentStatus.ACTIVE},
                    )

                if join_request.child.user_id:
                    notify_user(
                        join_request.child.user, NotificationType.ENROLLMENT_UPDATE,
                        title="Rattachement " + ("approuvé" if approve else "refusé"),
                        body=f"{establishment.school_name} a traité votre demande suite au rapport d'admission.",
                    )
                results.append({"join_request_id": join_request_id, "success": True})
            except (EstablishmentJoinRequest.DoesNotExist, ValueError) as exc:
                results.append({"join_request_id": join_request_id, "success": False, "error": str(exc)})

        return Response({
            "processed": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "results": results,
        })
