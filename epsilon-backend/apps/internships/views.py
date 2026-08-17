from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Enrollment, EnrollmentStatus
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import User, UserRole

from .models import (
    CompanyReview,
    ConventionStatus,
    EvaluatorType,
    InternshipApplication,
    InternshipApplicationStatus,
    InternshipConvention,
    InternshipJournal,
    InternshipOffer,
)
from .serializers import (
    CompanyReviewSerializer,
    InternshipApplicationSerializer,
    InternshipConventionSerializer,
    InternshipEvaluationSerializer,
    InternshipJournalSerializer,
    InternshipOfferSerializer,
)


def _require_company(user):
    if not user.has_role(UserRole.COMPANY):
        raise PermissionDenied("Réservé aux entreprises.")


def _require_company_or_staff(user):
    """Symétrique à _require_director_or_staff côté emploi — un
    administrateur peut modérer ou publier au nom de n'importe quelle
    entreprise."""
    if not (user.has_role(UserRole.COMPANY) or user.is_staff):
        raise PermissionDenied("Réservé aux entreprises ou aux administrateurs.")


def _require_director(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux établissements.")


def _require_director_owns_child(child, director):
    exists = Enrollment.objects.filter(
        child=child, status=EnrollmentStatus.ACTIVE,
        school_class__track__department__establishment__user=director,
    ).exists()
    if not exists:
        raise PermissionDenied("Cet élève n'est pas inscrit dans une classe de votre établissement.")


def _resolve_child_school_user(child):
    """Établissement de rattachement d'un élève qui candidate lui-même —
    l'école reste renseignée comme intermédiaire même quand c'est l'élève
    qui déclenche la candidature, jamais l'entreprise en direct."""
    enrollment = (
        Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
        .select_related("school_class__track__department__establishment__user")
        .first()
    )
    if not enrollment:
        raise PermissionDenied("Vous devez être inscrit dans une classe pour candidater.")
    return enrollment.school_class.track.department.establishment.user


class InternshipOfferViewSet(viewsets.ModelViewSet):
    """Offres de stage — catalogue public en lecture, gérées par
    l'entreprise qui les a publiées."""

    serializer_class = InternshipOfferSerializer
    pagination_class = None

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        base = InternshipOffer.objects.select_related("company__company_profile")

        if self.action == "list":
            if user.is_authenticated and user.is_staff:
                qs = base
            elif user.is_authenticated and user.has_role(UserRole.COMPANY):
                qs = base.filter(company=user)
            else:
                qs = base.filter(is_active=True)
        elif self.action == "retrieve":
            if user.is_authenticated and user.is_staff:
                qs = base
            elif user.is_authenticated and user.has_role(UserRole.COMPANY):
                qs = base.filter(Q(is_active=True) | Q(company=user))
            else:
                qs = base.filter(is_active=True)
        else:
            _require_company_or_staff(user)
            qs = base if user.is_staff else base.filter(company=user)

        params = self.request.query_params
        if params.get("domain"):
            qs = qs.filter(domain__iexact=params["domain"])
        if params.get("city"):
            qs = qs.filter(city__iexact=params["city"])
        if params.get("level"):
            qs = qs.filter(level=params["level"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        _require_company_or_staff(user)
        if user.is_staff and not user.has_role(UserRole.COMPANY):
            company_id = self.request.data.get("company_id")
            company = get_object_or_404(User, pk=company_id, primary_role=UserRole.COMPANY) if company_id else None
            if not company:
                raise ValidationError({"company_id": "Un administrateur doit préciser l'entreprise (company_id)."})
        else:
            company = user
        serializer.save(company=company)


class OfferApplicationsView(generics.ListCreateAPIView):
    """Candidatures à une offre de stage — l'entreprise (propriétaire)
    consulte, l'établissement candidate au nom d'un élève inscrit."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InternshipApplicationSerializer
    pagination_class = None

    def _get_offer(self):
        try:
            return InternshipOffer.objects.select_related("company").get(id=self.kwargs["offer_id"])
        except InternshipOffer.DoesNotExist:
            raise Http404

    def get_queryset(self):
        offer = self._get_offer()
        if offer.company_id != self.request.user.id:
            raise PermissionDenied("Réservé à l'entreprise ayant publié cette offre.")
        return InternshipApplication.objects.filter(offer=offer).select_related("student", "school", "offer")

    def perform_create(self, serializer):
        offer = self._get_offer()
        user = self.request.user
        child = serializer.validated_data["student"]

        # Deux voies légitimes : l'établissement candidate au nom d'un
        # élève inscrit, ou l'élève (compte activé) candidate lui-même —
        # dans les deux cas l'école reste renseignée comme intermédiaire
        # (school=), jamais l'entreprise et l'élève ne sont mis en contact
        # avant l'ouverture du canal de stage à l'acceptation.
        child_profile = getattr(user, "child_profile", None)
        is_self_application = child_profile is not None and child_profile.id == child.id
        if is_self_application:
            school_user = _resolve_child_school_user(child)
        else:
            _require_director(user)
            _require_director_owns_child(child, user)
            school_user = user

        if InternshipApplication.objects.filter(offer=offer, student=child).exists():
            raise ValidationError("Une candidature existe déjà pour cet élève sur cette offre.")
        application = serializer.save(offer=offer, school=school_user)
        notify_user(
            offer.company,
            NotificationType.STAGE_UPDATE,
            title="Nouvelle candidature de stage",
            body=f"{school_user.get_full_name()} candidate pour {child.first_name} à \"{offer.title}\".",
            data={"application_id": str(application.id)},
        )


class MyInternshipApplicationsView(generics.ListAPIView):
    """Candidatures soumises par l'établissement connecté, ou par l'élève
    lui-même pour ses propres candidatures directes."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InternshipApplicationSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if user.has_role(UserRole.DIRECTOR):
            return InternshipApplication.objects.filter(school=user).select_related(
                "student", "offer", "offer__company"
            )
        child = getattr(user, "child_profile", None)
        if child:
            return InternshipApplication.objects.filter(student=child).select_related(
                "student", "offer", "offer__company"
            )
        raise PermissionDenied("Réservé aux établissements et aux élèves.")


class InternshipApplicationDetailView(generics.RetrieveUpdateAPIView):
    """Détail d'une candidature — l'entreprise propriétaire de l'offre
    accepte ou refuse. Une acceptation génère la convention de stage."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InternshipApplicationSerializer

    def get_queryset(self):
        return InternshipApplication.objects.select_related(
            "offer", "offer__company", "student", "school"
        )

    def get_object(self):
        application = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        if application.offer.company_id != self.request.user.id:
            raise PermissionDenied("Réservé à l'entreprise ayant publié cette offre.")
        return application

    def update(self, request, *args, **kwargs):
        application = self.get_object()
        new_status = request.data.get("status")
        if new_status not in (InternshipApplicationStatus.ACCEPTED, InternshipApplicationStatus.REJECTED):
            raise ValidationError({"status": "Statut invalide."})

        application.status = new_status
        application.reviewed_at = timezone.now()
        application.save(update_fields=["status", "reviewed_at"])

        if new_status == InternshipApplicationStatus.ACCEPTED:
            convention, _ = InternshipConvention.objects.get_or_create(application=application)
            from apps.messaging.services import ensure_internship_channel

            # Le canal de stage doit exister dès l'acceptation — l'entreprise
            # y génère et dépose la convention avant même la signature, pas
            # seulement une fois le stage officiellement complet.
            ensure_internship_channel(convention)
            notify_user(
                application.school,
                NotificationType.STAGE_UPDATE,
                title="Stage confirmé !",
                body=(
                    f"{application.offer.company.get_full_name()} a accepté {application.student.first_name} "
                    f"pour \"{application.offer.title}\"."
                ),
                data={"convention_id": str(convention.id)},
            )
        else:
            notify_user(
                application.school,
                NotificationType.STAGE_UPDATE,
                title="Candidature de stage refusée",
                body=f"\"{application.offer.title}\" — {application.offer.company.get_full_name()}.",
                data={"application_id": str(application.id)},
            )

        return Response(self.get_serializer(application).data)


class MyConventionsView(generics.ListAPIView):
    """Conventions de stage de l'utilisateur connecté (établissement ou
    entreprise)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InternshipConventionSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        qs = InternshipConvention.objects.select_related(
            "application", "application__student", "application__offer",
            "application__offer__company", "application__school",
        )
        if user.has_role(UserRole.DIRECTOR):
            return qs.filter(application__school=user)
        if user.has_role(UserRole.COMPANY):
            return qs.filter(application__offer__company=user)
        child = getattr(user, "child_profile", None)
        if child:
            return qs.filter(application__student=child)
        raise PermissionDenied("Réservé aux établissements, entreprises et élèves concernés.")


def _get_convention(convention_id):
    try:
        return InternshipConvention.objects.select_related(
            "application", "application__school", "application__offer", "application__offer__company",
            "application__student",
        ).get(id=convention_id)
    except InternshipConvention.DoesNotExist:
        raise Http404


def _require_convention_party(convention, user):
    application = convention.application
    if user.id not in (application.school_id, application.offer.company_id):
        raise PermissionDenied("Réservé aux parties de cette convention.")


def _require_convention_company(convention, user):
    if convention.application.offer.company_id != user.id:
        raise PermissionDenied("Réservé à l'entreprise d'accueil.")


class SignConventionView(APIView):
    """Signature d'une convention par l'une des deux parties — la
    convention passe "complète" une fois signée des deux côtés."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        convention = _get_convention(pk)
        application = convention.application
        user = request.user

        if user.id == application.school_id:
            convention.signed_by_school_at = timezone.now()
        elif user.id == application.offer.company_id:
            convention.signed_by_company_at = timezone.now()
        else:
            raise PermissionDenied("Réservé aux parties de cette convention.")

        if convention.signed_by_school_at and convention.signed_by_company_at:
            convention.status = ConventionStatus.COMPLETE
        elif convention.signed_by_school_at:
            convention.status = ConventionStatus.SIGNED_SCH
        elif convention.signed_by_company_at:
            convention.status = ConventionStatus.SIGNED_ENT
        convention.save(update_fields=["signed_by_school_at", "signed_by_company_at", "status"])

        if convention.status == ConventionStatus.COMPLETE:
            from apps.messaging.services import ensure_internship_channel

            ensure_internship_channel(convention)

        return Response(InternshipConventionSerializer(convention).data)


class GenerateConventionPdfView(APIView):
    """L'entreprise (responsable du stage) génère — ou régénère, si le
    poste ou les couleurs de marque ont changé — le PDF de convention aux
    couleurs de son profil, et le dépose automatiquement dans le canal de
    stage partagé avec l'élève."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        convention = _get_convention(pk)
        _require_convention_company(convention, request.user)

        position_title = request.data.get("position_title")
        if position_title:
            convention.position_title = position_title
            convention.save(update_fields=["position_title"])

        from .pdf import generate_and_attach_convention_pdf

        generate_and_attach_convention_pdf(convention)
        convention.refresh_from_db()
        return Response(InternshipConventionSerializer(convention).data)


class ConventionJournalView(generics.ListCreateAPIView):
    """Journal de stage — tenu par l'entreprise d'accueil, consultable par
    les deux parties."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InternshipJournalSerializer
    pagination_class = None

    def get_queryset(self):
        convention = _get_convention(self.kwargs["convention_id"])
        _require_convention_party(convention, self.request.user)
        return InternshipJournal.objects.filter(convention=convention)

    def perform_create(self, serializer):
        convention = _get_convention(self.kwargs["convention_id"])
        _require_convention_company(convention, self.request.user)
        serializer.save(convention=convention)


class ConventionEvaluationView(generics.ListCreateAPIView):
    """Évaluation de fin de stage par l'entreprise d'accueil."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InternshipEvaluationSerializer
    pagination_class = None

    def get_queryset(self):
        convention = _get_convention(self.kwargs["convention_id"])
        _require_convention_party(convention, self.request.user)
        return convention.evaluations.all()

    def perform_create(self, serializer):
        convention = _get_convention(self.kwargs["convention_id"])
        _require_convention_company(convention, self.request.user)
        serializer.save(convention=convention, evaluator_type=EvaluatorType.COMPANY)
        notify_user(
            convention.application.school,
            NotificationType.STAGE_UPDATE,
            title="Évaluation de stage disponible",
            body=(
                f"{convention.application.offer.company.get_full_name()} a évalué "
                f"{convention.application.student.first_name}."
            ),
            data={"convention_id": str(convention.id)},
        )


class SubmitCompanyReviewView(APIView):
    """Avis réciproque du stagiaire sur l'entreprise — réservé au compte
    élève qui a réellement effectué CE stage, uniquement une fois la
    période de stage terminée (period_end passée), une seule fois par
    convention. Contrairement à EmployerReview, pas besoin d'anonymat :
    l'entreprise connaît déjà l'identité de son stagiaire par la
    convention elle-même."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, convention_id):
        convention = _get_convention(convention_id)
        child = getattr(request.user, "child_profile", None)
        if not child or convention.application.student_id != child.id:
            raise PermissionDenied("Réservé au stagiaire de cette convention.")
        if convention.application.offer.period_end > timezone.localdate():
            return Response(
                {"detail": "L'avis n'est disponible qu'une fois le stage terminé."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if CompanyReview.objects.filter(convention=convention).exists():
            return Response({"detail": "Un avis a déjà été déposé pour ce stage."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CompanyReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(convention=convention)

        notify_user(
            convention.application.offer.company,
            NotificationType.STAGE_UPDATE,
            title="Nouvel avis stagiaire",
            body=f"{child.first_name} a laissé un avis sur son stage chez vous.",
            data={"convention_id": str(convention.id)},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
