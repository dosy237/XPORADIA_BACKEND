from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.certification.serializers import MyCertificationStatusSerializer
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import User, UserRole

from .models import ApplicationStatus, JobApplication, JobListing, JobSeekingRequest, JobStatus, Recruitment
from .serializers import (
    JobApplicationSerializer,
    JobListingSerializer,
    JobSeekingRequestSerializer,
    RecruitmentSerializer,
)


def _require_director(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")


class JobListingViewSet(viewsets.ModelViewSet):
    """Offres d'emploi — catalogue public en lecture, gérées par le
    directeur qui les a publiées."""

    serializer_class = JobListingSerializer
    pagination_class = None

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        base = JobListing.objects.select_related("school__director_profile")

        if self.action == "list":
            # Un directeur connecté gère ses propres offres (tous statuts,
            # y compris brouillons) ; tout le monde d'autre parcourt le
            # catalogue public des offres actives.
            if user.is_authenticated and user.has_role(UserRole.DIRECTOR):
                qs = base.filter(school=user)
            else:
                qs = base.filter(status=JobStatus.ACTIVE)
        elif self.action == "retrieve":
            if user.is_authenticated and user.has_role(UserRole.DIRECTOR):
                qs = base.filter(Q(status=JobStatus.ACTIVE) | Q(school=user))
            else:
                qs = base.filter(status=JobStatus.ACTIVE)
        else:
            _require_director(user)
            qs = base.filter(school=user)

        params = self.request.query_params
        if params.get("subject"):
            qs = qs.filter(subject__iexact=params["subject"])
        if params.get("city"):
            qs = qs.filter(city__iexact=params["city"])
        if params.get("contract_type"):
            qs = qs.filter(contract_type=params["contract_type"])
        return qs

    def perform_create(self, serializer):
        _require_director(self.request.user)
        emails = serializer.validated_data.pop("targeted_teacher_emails", [])
        listing = serializer.save(school=self.request.user)
        self._target_teachers(listing, emails)

    def perform_update(self, serializer):
        emails = serializer.validated_data.pop("targeted_teacher_emails", None)
        listing = serializer.save()
        if emails is not None:
            self._target_teachers(listing, emails)

    def _target_teachers(self, listing, emails):
        if not emails:
            return
        teachers = User.objects.filter(email__in=[e.lower() for e in emails], is_active=True)
        listing.targeted_teachers.add(*teachers)
        for teacher in teachers:
            notify_user(
                teacher,
                NotificationType.NEW_JOB_OFFER,
                title="Une offre pourrait vous intéresser",
                body=f"{listing.school.get_full_name()} vous propose : \"{listing.title}\" ({listing.city}).",
                data={"listing_id": str(listing.id)},
            )

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        listing = self.get_object()
        listing.status = JobStatus.ACTIVE
        listing.published_at = timezone.now()
        listing.save(update_fields=["status", "published_at"])
        return Response(self.get_serializer(listing).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        listing = self.get_object()
        listing.status = JobStatus.CLOSED
        listing.save(update_fields=["status"])
        return Response(self.get_serializer(listing).data)


class ListingApplicationsView(generics.ListCreateAPIView):
    """Candidatures à une offre — le directeur (propriétaire) consulte,
    l'enseignant candidate."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JobApplicationSerializer
    pagination_class = None

    def _get_listing(self):
        try:
            return JobListing.objects.select_related("school").get(id=self.kwargs["listing_id"])
        except JobListing.DoesNotExist:
            raise Http404

    def get_queryset(self):
        listing = self._get_listing()
        if listing.school_id != self.request.user.id:
            raise PermissionDenied("Réservé à l'établissement ayant publié cette offre.")
        return JobApplication.objects.filter(listing=listing).select_related("teacher", "listing")

    def perform_create(self, serializer):
        listing = self._get_listing()
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        if JobApplication.objects.filter(listing=listing, teacher=self.request.user).exists():
            raise ValidationError("Vous avez déjà postulé à cette offre.")
        application = serializer.save(listing=listing, teacher=self.request.user)
        notify_user(
            listing.school,
            NotificationType.NEW_JOB_OFFER,
            title="Nouvelle candidature",
            body=f"{application.teacher.get_full_name()} a postulé à \"{listing.title}\".",
            data={"application_id": str(application.id)},
        )


class MyJobApplicationsView(generics.ListAPIView):
    """Candidatures de l'enseignant connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JobApplicationSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return JobApplication.objects.filter(teacher=self.request.user).select_related("teacher", "listing")


_STATUS_MESSAGES = {
    ApplicationStatus.VIEWED: "Votre candidature a été consultée",
    ApplicationStatus.INTERVIEW: "Vous êtes invité(e) à un entretien",
    ApplicationStatus.REJECTED: "Votre candidature n'a pas été retenue",
}


class JobApplicationDetailView(generics.RetrieveUpdateAPIView):
    """Détail d'une candidature — le directeur propriétaire de l'offre fait
    évoluer son statut. Le passage à "acceptée" exige un salaire convenu et
    crée le Recrutement correspondant."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JobApplicationSerializer

    def get_queryset(self):
        return JobApplication.objects.select_related("teacher", "listing", "listing__school")

    def get_object(self):
        application = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        if application.listing.school_id != self.request.user.id:
            raise PermissionDenied("Réservé à l'établissement ayant publié cette offre.")
        return application

    def update(self, request, *args, **kwargs):
        application = self.get_object()
        new_status = request.data.get("status")
        if new_status not in ApplicationStatus.values:
            raise ValidationError({"status": "Statut invalide."})

        if new_status == ApplicationStatus.ACCEPTED:
            salary_agreed = request.data.get("salary_agreed")
            if not salary_agreed:
                raise ValidationError({"salary_agreed": "Ce champ est requis pour accepter une candidature."})
            recruitment = Recruitment.objects.create(
                school=application.listing.school,
                teacher=application.teacher,
                application=application,
                salary_agreed=salary_agreed,
            )
            application.status = new_status
            application.save(update_fields=["status"])
            notify_user(
                application.teacher,
                NotificationType.RECRUITMENT,
                title="Recrutement confirmé !",
                body=(
                    f"{application.listing.school.get_full_name()} vous a recruté(e) "
                    f"pour \"{application.listing.title}\"."
                ),
                data={"recruitment_id": str(recruitment.id)},
            )
            return Response(self.get_serializer(application).data)

        update_fields = ["status"]
        if new_status == ApplicationStatus.VIEWED and not application.viewed_at:
            application.viewed_at = timezone.now()
            update_fields.append("viewed_at")

        application.status = new_status
        application.save(update_fields=update_fields)

        message = _STATUS_MESSAGES.get(new_status)
        if message:
            notify_user(
                application.teacher,
                NotificationType.APPLICATION_VIEWED,
                title=message,
                body=f"\"{application.listing.title}\" — {application.listing.school.get_full_name()}.",
                data={"application_id": str(application.id)},
            )

        return Response(self.get_serializer(application).data)


class MyRecruitmentsView(generics.ListAPIView):
    """Recrutements confirmés de l'enseignant connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RecruitmentSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return Recruitment.objects.filter(teacher=self.request.user).select_related("teacher")


class JobSeekingRequestListCreateView(generics.ListCreateAPIView):
    """Demandes d'emploi publiées par des enseignants Or — consultables
    publiquement (recrutement par les établissements), publiables
    uniquement par un enseignant ayant atteint ce niveau."""

    serializer_class = JobSeekingRequestSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        qs = JobSeekingRequest.objects.filter(is_active=True).select_related("teacher")
        city = self.request.query_params.get("city")
        if city:
            qs = qs.filter(city__iexact=city)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        status_data = MyCertificationStatusSerializer.build(user)
        if status_data["current_level"] != "gold":
            raise PermissionDenied(
                "Cette fonctionnalité est un privilège réservé aux enseignants de niveau Or."
            )
        JobSeekingRequest.objects.filter(teacher=user, is_active=True).update(is_active=False)
        serializer.save(teacher=user)


class MyJobSeekingRequestView(APIView):
    """Demande d'emploi active de l'enseignant connecté, et sa
    désactivation."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        request_obj = JobSeekingRequest.objects.filter(teacher=request.user, is_active=True).first()
        if not request_obj:
            return Response(None)
        return Response(JobSeekingRequestSerializer(request_obj).data)

    def delete(self, request):
        JobSeekingRequest.objects.filter(teacher=request.user, is_active=True).update(is_active=False)
        return Response(status=204)
