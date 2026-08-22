from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.certification.constants import POINTS_THRESHOLDS
from apps.certification.models import CertificationLevel
from apps.certification.serializers import MyCertificationStatusSerializer
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import User, UserRole

from .models import (
    ApplicationStatus,
    ContractType,
    EmployerReview,
    EstablishmentInvoice,
    EstablishmentInvoiceStatus,
    JobApplication,
    JobListing,
    JobSeekingRequest,
    JobStatus,
    PayrollEntry,
    Recruitment,
    WalletTransaction,
    WorkedHours,
    WorkedHoursStatus,
)
from .serializers import (
    CreateEmployerReviewSerializer,
    EstablishmentEmploymentHistorySerializer,
    EstablishmentInvoiceSerializer,
    JobApplicationSerializer,
    JobListingSerializer,
    JobSeekingRequestSerializer,
    RecruitmentSerializer,
    ReviewWorkedHoursSerializer,
    WalletTransactionSerializer,
    WorkedHoursSerializer,
)


def _require_director(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")


def _require_director_or_staff(user):
    """Un administrateur peut modérer ou publier au nom de n'importe quel
    établissement — jamais besoin d'usurper un compte directeur pour
    corriger une offre inappropriée."""
    if not (user.has_role(UserRole.DIRECTOR) or user.is_staff):
        raise PermissionDenied("Réservé aux directeurs d'établissement ou aux administrateurs.")


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
            # y compris brouillons) ; un admin voit TOUT, tous
            # établissements confondus (modération) ; tout le monde
            # d'autre parcourt le catalogue public des offres actives.
            if user.is_authenticated and user.is_staff:
                qs = base
            elif user.is_authenticated and user.has_role(UserRole.DIRECTOR):
                qs = base.filter(school=user)
            else:
                qs = base.filter(status=JobStatus.ACTIVE)
        elif self.action == "retrieve":
            if user.is_authenticated and user.is_staff:
                qs = base
            elif user.is_authenticated and user.has_role(UserRole.DIRECTOR):
                qs = base.filter(Q(status=JobStatus.ACTIVE) | Q(school=user))
            else:
                qs = base.filter(status=JobStatus.ACTIVE)
        else:
            _require_director_or_staff(user)
            qs = base if user.is_staff else base.filter(school=user)

        params = self.request.query_params
        if params.get("subject"):
            qs = qs.filter(subject__iexact=params["subject"])
        if params.get("city"):
            qs = qs.filter(city__iexact=params["city"])
        if params.get("contract_type"):
            qs = qs.filter(contract_type=params["contract_type"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        _require_director_or_staff(user)
        emails = serializer.validated_data.pop("targeted_teacher_emails", [])
        if user.is_staff and not user.has_role(UserRole.DIRECTOR):
            school_id = self.request.data.get("school_id")
            school = get_object_or_404(User, pk=school_id, primary_role=UserRole.DIRECTOR) if school_id else None
            if not school:
                raise ValidationError({"school_id": "Un administrateur doit préciser l'établissement (school_id)."})
        else:
            school = user
        listing = serializer.save(school=school)
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

        # Canal directeur↔enseignant ouvert dès la candidature — jamais de
        # contact direct en dehors de Xporadia, même principe que le canal
        # de stage. C'est ici, et seulement ici, que la mise en relation
        # se fait, et que la commission de recrutement se justifie.
        from apps.messaging.services import get_or_create_direct_channel

        get_or_create_direct_channel(listing.school, self.request.user)

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
            contract_type = application.listing.contract_type
            recruitment_kwargs = dict(
                school=application.listing.school,
                teacher=application.teacher,
                application=application,
                contract_type=contract_type,
            )
            if contract_type == ContractType.CDI:
                salary_agreed = request.data.get("salary_agreed")
                if not salary_agreed:
                    raise ValidationError({"salary_agreed": "Ce champ est requis pour un CDI."})
                recruitment_kwargs["salary_agreed"] = salary_agreed
            else:
                hourly_rate_teacher = request.data.get("hourly_rate_teacher")
                hourly_rate_billed = request.data.get("hourly_rate_billed")
                if not hourly_rate_teacher or not hourly_rate_billed:
                    raise ValidationError({
                        "hourly_rate_teacher": "Requis pour un contrat CDD/Vacation/Intérim.",
                        "hourly_rate_billed": "Requis pour un contrat CDD/Vacation/Intérim.",
                    })
                if int(hourly_rate_billed) < int(hourly_rate_teacher):
                    raise ValidationError(
                        {"hourly_rate_billed": "Le tarif facturé à l'établissement ne peut pas être inférieur "
                                                "au tarif versé à l'enseignant."}
                    )
                recruitment_kwargs["hourly_rate_teacher"] = hourly_rate_teacher
                recruitment_kwargs["hourly_rate_billed"] = hourly_rate_billed

            recruitment = Recruitment.objects.create(**recruitment_kwargs)
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
                body=f"\"{application.listing.title}\" : {application.listing.school.get_full_name()}.",
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


class MySchoolRecruitmentsView(generics.ListAPIView):
    """Symétrique côté établissement : les enseignants que le directeur
    connecté a recrutés — alimente l'écran de validation des heures
    déclarées (un directeur doit d'abord savoir QUI a un contrat aux
    heures avant de pouvoir valider quoi que ce soit)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RecruitmentSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.DIRECTOR):
            raise PermissionDenied("Réservé aux établissements.")
        return Recruitment.objects.filter(school=self.request.user).select_related("teacher")


class CreateEmployerReviewView(APIView):
    """Avis anonyme de l'enseignant sur l'établissement où il a travaillé —
    disponible 30 jours après confirmation du recrutement, une seule fois.
    Anonyme par construction : EmployerReview ne porte aucun champ auteur,
    seulement le recrutement, jamais exposé sur la fiche publique."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, recruitment_id):
        try:
            recruitment = Recruitment.objects.select_related("teacher").get(id=recruitment_id)
        except Recruitment.DoesNotExist:
            raise Http404
        if recruitment.teacher_id != request.user.id:
            raise PermissionDenied("Réservé à l'enseignant concerné par ce recrutement.")
        if EmployerReview.objects.filter(recruitment=recruitment).exists():
            return Response({"detail": "Un avis a déjà été déposé pour ce recrutement."}, status=status.HTTP_400_BAD_REQUEST)

        from .constants import REVIEW_MIN_DAYS_AFTER_RECRUITMENT

        days_since = (timezone.now() - recruitment.confirmed_at).days
        if days_since < REVIEW_MIN_DAYS_AFTER_RECRUITMENT:
            return Response(
                {"detail": f"L'avis n'est disponible que {REVIEW_MIN_DAYS_AFTER_RECRUITMENT} jours après le recrutement."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CreateEmployerReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(recruitment=recruitment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TeacherEmploymentHistoryView(generics.ListAPIView):
    """Historique d'emploi PUBLIC d'un enseignant — établissements actuels
    et passés, sans aucune donnée salariale (voir le serializer dédié)."""

    permission_classes = [permissions.AllowAny]
    serializer_class = EstablishmentEmploymentHistorySerializer
    pagination_class = None

    def get_queryset(self):
        return Recruitment.objects.filter(teacher_id=self.kwargs["teacher_id"]).select_related(
            "school__director_profile"
        )


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
        # "Au moins Or" (Or, Platine ou Diamant) — pas "exactement Or", pour
        # ne pas exclure les enseignants qui ont dépassé ce palier.
        if status_data["total_points"] < POINTS_THRESHOLDS[CertificationLevel.GOLD]:
            raise PermissionDenied(
                "Cette fonctionnalité est un privilège réservé aux enseignants de niveau Or ou plus."
            )
        JobSeekingRequest.objects.filter(teacher=user, is_active=True).update(is_active=False)
        serializer.save(teacher=user)


class MyJobSeekingRequestView(APIView):
    """Demande d'emploi active de l'enseignant connecté, et sa
    désactivation."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        request_obj = JobSeekingRequest.objects.filter(teacher=request.user, is_active=True).first()
        return Response({
            "request": JobSeekingRequestSerializer(request_obj, context={"request": request}).data if request_obj else None,
        })

    def delete(self, request):
        JobSeekingRequest.objects.filter(teacher=request.user, is_active=True).update(is_active=False)
        return Response(status=204)


def _get_recruitment_for_hours(recruitment_id, user):
    """Un enseignant ne déclare que sur SES recrutements, un directeur ne
    consulte/valide que sur ceux de son établissement."""
    try:
        recruitment = Recruitment.objects.select_related("teacher", "school").get(id=recruitment_id)
    except Recruitment.DoesNotExist:
        raise Http404
    if recruitment.teacher_id != user.id and recruitment.school_id != user.id:
        raise PermissionDenied("Ce recrutement ne vous concerne pas.")
    return recruitment


class WorkedHoursListCreateView(generics.ListCreateAPIView):
    """Déclaration et consultation des heures travaillées pour un
    recrutement — jamais pertinent pour un CDI (salaire fixe, voir
    Recruitment.requires_declared_hours)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WorkedHoursSerializer
    pagination_class = None

    def get_queryset(self):
        recruitment = _get_recruitment_for_hours(self.kwargs["recruitment_id"], self.request.user)
        return WorkedHours.objects.filter(recruitment=recruitment).order_by("-date")

    def perform_create(self, serializer):
        recruitment = _get_recruitment_for_hours(self.kwargs["recruitment_id"], self.request.user)
        if recruitment.teacher_id != self.request.user.id:
            raise PermissionDenied("Seul l'enseignant concerné peut déclarer ses heures.")
        if not recruitment.requires_declared_hours:
            raise PermissionDenied("Ce recrutement est en CDI — pas de déclaration d'heures nécessaire.")
        if WorkedHours.objects.filter(recruitment=recruitment, date=serializer.validated_data["date"]).exists():
            raise ValidationError("Des heures ont déjà été déclarées pour cette date.")
        serializer.save(recruitment=recruitment)
        notify_user(
            recruitment.school,
            NotificationType.ENROLLMENT_UPDATE,
            title="Heures à valider",
            body=f"{recruitment.teacher.get_full_name()} a déclaré des heures pour le {serializer.validated_data['date']}.",
        )


class ReviewWorkedHoursView(APIView):
    """Validation ou rejet d'une déclaration d'heures — réservé à
    l'établissement concerné. Sans validation, ces heures n'entreront
    jamais dans la paie de fin de mois."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            entry = WorkedHours.objects.select_related("recruitment__teacher", "recruitment__school").get(pk=pk)
        except WorkedHours.DoesNotExist:
            raise Http404
        if entry.recruitment.school_id != request.user.id:
            raise PermissionDenied("Réservé à l'établissement concerné.")
        if entry.status != WorkedHoursStatus.PENDING:
            return Response({"detail": "Cette déclaration a déjà été traitée."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ReviewWorkedHoursSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        entry.status = WorkedHoursStatus.APPROVED if serializer.validated_data["approve"] else WorkedHoursStatus.REJECTED
        entry.reviewed_by = request.user
        entry.reviewed_at = timezone.now()
        entry.rejection_reason = serializer.validated_data.get("rejection_reason", "")
        entry.save(update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason"])

        if entry.status == WorkedHoursStatus.REJECTED:
            notify_user(
                entry.recruitment.teacher,
                NotificationType.ENROLLMENT_UPDATE,
                title="Heures rejetées",
                body=f"Vos heures du {entry.date} ont été rejetées : {entry.rejection_reason or 'motif non précisé'}.",
            )
        return Response(WorkedHoursSerializer(entry).data)


class MySalaryBenchmarkView(APIView):
    """Repère salarial PRIVÉ — jamais affiché à quiconque d'autre que
    l'enseignant lui-même. Compare son revenu actuel à la fourchette
    recommandée du cahier des charges pour son niveau de certification :
    un outil de négociation concret, pas une donnée décorative."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")

        from apps.certification.constants import SALARY_RANGES_FCFA_PER_MONTH
        from apps.users.serializers import _current_certification_level

        level = _current_certification_level(request.user)
        salary_range = SALARY_RANGES_FCFA_PER_MONTH.get(level) if level else None

        current_income = None
        income_source = None

        cdi_recruitment = Recruitment.objects.filter(
            teacher=request.user, contract_type=ContractType.CDI
        ).order_by("-confirmed_at").first()
        if cdi_recruitment and cdi_recruitment.salary_agreed:
            current_income = cdi_recruitment.salary_agreed
            income_source = "cdi"
        else:
            last_payroll = PayrollEntry.objects.filter(
                recruitment__teacher=request.user
            ).order_by("-period_year", "-period_month").first()
            if last_payroll:
                current_income = last_payroll.gross_amount
                income_source = "hourly_last_month"

        position = None
        if current_income is not None and salary_range:
            low, high = salary_range
            if current_income < low:
                position = "below"
            elif current_income > high:
                position = "above"
            else:
                position = "within"

        return Response({
            "current_level": level,
            "salary_range_min": salary_range[0] if salary_range else None,
            "salary_range_max": salary_range[1] if salary_range else None,
            "current_income": current_income,
            "income_source": income_source,
            "position": position,
        })


class MyWalletView(APIView):
    """Portefeuille de l'enseignant connecté — solde (toujours recalculé
    depuis l'historique, jamais stocké séparément) et détail des paies
    mensuelles perçues."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        transactions = WalletTransaction.objects.filter(teacher=request.user).select_related(
            "payroll_entry__recruitment__school__director_profile"
        )
        balance = sum(t.amount for t in transactions)
        return Response({
            "balance": balance,
            "transactions": WalletTransactionSerializer(transactions, many=True).data,
        })


class MyInvoicesView(generics.ListAPIView):
    """Factures mensuelles de l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EstablishmentInvoiceSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.DIRECTOR):
            raise PermissionDenied("Réservé aux établissements.")
        return EstablishmentInvoice.objects.filter(
            establishment__user=self.request.user
        ).select_related("payment")


class PayInvoiceView(APIView):
    """Règlement d'une facture — Mobile Money ou carte bancaire (simulés,
    voir apps.payments.services). Le paiement va directement à Xporadia,
    pas de séquestre : il n'y a pas de contrepartie à libérer."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, invoice_id):
        from apps.payments.models import MobileOperator, PaymentType
        from apps.payments.services import confirm_payment_completed, initiate_payment

        invoice = get_object_or_404(
            EstablishmentInvoice, pk=invoice_id, establishment__user=request.user
        )
        if invoice.status == EstablishmentInvoiceStatus.PAID:
            return Response({"detail": "Cette facture est déjà réglée."}, status=status.HTTP_400_BAD_REQUEST)

        method = request.data.get("method")
        if method == "bank_card":
            card_number = request.data.get("card_number", "")
            card_holder_name = request.data.get("card_holder_name", "")
            if not card_number or not card_holder_name:
                raise ValidationError({"card_number": "Numéro de carte et titulaire requis."})
            payment = initiate_payment(
                user=request.user, amount=invoice.total_amount, payment_type=PaymentType.PAYROLL_INVOICE,
                card_last4=card_number[-4:], card_holder_name=card_holder_name,
                content_object=invoice,
            )
        else:
            operator = request.data.get("operator")
            phone_number = request.data.get("phone_number")
            if operator not in MobileOperator.values or not phone_number:
                raise ValidationError({"operator": "Opérateur Mobile Money et numéro requis."})
            payment = initiate_payment(
                user=request.user, amount=invoice.total_amount, payment_type=PaymentType.PAYROLL_INVOICE,
                operator=operator, phone_number=phone_number,
                content_object=invoice,
            )

        confirm_payment_completed(payment)
        invoice.payment = payment
        invoice.status = EstablishmentInvoiceStatus.PAID
        invoice.paid_at = timezone.now()
        invoice.save(update_fields=["payment", "status", "paid_at"])

        return Response(EstablishmentInvoiceSerializer(invoice).data)
