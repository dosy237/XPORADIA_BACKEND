from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import Child, DirectorProfile, UserRole

from . import services
from .models import FeeInstallment, FeePayment, FeeSchedule
from .serializers import FeeInstallmentSerializer, FeePaymentSerializer, FeeScheduleSerializer


def _get_establishment(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")
    return get_object_or_404(DirectorProfile, user=user)


def _get_child_in_establishment(child_id, establishment):
    from apps.academics.models import Enrollment, EnrollmentStatus

    enrollment = Enrollment.objects.filter(
        child_id=child_id,
        status=EnrollmentStatus.ACTIVE,
        school_class__track__department__establishment=establishment,
    ).select_related("child").first()
    if not enrollment:
        raise Http404
    return enrollment.child


class FeeScheduleView(APIView):
    """Échéancier de l'établissement du directeur connecté, pour une
    année scolaire donnée (?school_year=2025-2026) — un seul par
    établissement et par année, créé à la demande."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        establishment = _get_establishment(request.user)
        school_year = request.query_params.get("school_year")
        if not school_year:
            raise ValidationError({"school_year": "Paramètre obligatoire."})
        schedule = FeeSchedule.objects.filter(establishment=establishment, school_year=school_year).first()
        if not schedule:
            return Response({"detail": "Aucun échéancier pour cette année scolaire."}, status=404)
        return Response(FeeScheduleSerializer(schedule).data)

    def post(self, request):
        establishment = _get_establishment(request.user)
        school_year = (request.data.get("school_year") or "").strip()
        if not school_year:
            raise ValidationError({"school_year": "Obligatoire."})
        schedule, _ = FeeSchedule.objects.get_or_create(establishment=establishment, school_year=school_year)
        return Response(FeeScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


class FeeInstallmentListCreateView(generics.ListCreateAPIView):
    """Tranches d'un échéancier — réservé au directeur de cet
    établissement."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FeeInstallmentSerializer
    pagination_class = None

    def _get_schedule(self):
        establishment = _get_establishment(self.request.user)
        schedule = get_object_or_404(FeeSchedule, pk=self.kwargs["schedule_id"])
        if schedule.establishment_id != establishment.id:
            raise PermissionDenied("Cet échéancier n'appartient pas à votre établissement.")
        return schedule

    def get_queryset(self):
        return self._get_schedule().installments.all()

    def perform_create(self, serializer):
        serializer.save(fee_schedule=self._get_schedule())


class FeeInstallmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Modification/suppression d'une tranche existante — réservé au
    directeur de l'établissement propriétaire de l'échéancier."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FeeInstallmentSerializer

    def get_queryset(self):
        return FeeInstallment.objects.select_related("fee_schedule__establishment")

    def get_object(self):
        installment = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        establishment = _get_establishment(self.request.user)
        if installment.fee_schedule.establishment_id != establishment.id:
            raise PermissionDenied("Cette tranche n'appartient pas à votre établissement.")
        return installment


class ChildFeeStatusView(APIView):
    """Fiche de paiement d'un élève : chaque tranche de l'échéancier
    applicable avec son statut déduit, et l'historique des paiements —
    réservé au directeur de l'établissement où l'élève est inscrit."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, child_id):
        establishment = _get_establishment(request.user)
        child = _get_child_in_establishment(child_id, establishment)
        schedule = services.active_fee_schedule_for_child(child)
        if not schedule:
            return Response({"schedule": None, "installments": [], "payments": []})

        installments_data = []
        for installment in schedule.installments.all():
            info = services.installment_status(installment, child)
            installments_data.append({
                "installment": FeeInstallmentSerializer(installment).data,
                "amount_paid": info["amount_paid"],
                "amount_due": info["amount_due"],
                "status": info["status"],
            })
        payments = FeePayment.objects.filter(child=child, fee_installment__fee_schedule=schedule).select_related(
            "recorded_by"
        )
        return Response({
            "schedule": FeeScheduleSerializer(schedule).data,
            "installments": installments_data,
            "payments": FeePaymentSerializer(payments, many=True).data,
        })


class RecordFeePaymentView(APIView):
    """Enregistrement d'un versement sur une tranche, pour un élève —
    montant et canal, rien de plus (voir spécification : "pas de
    formulaire long")."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, child_id, installment_id):
        establishment = _get_establishment(request.user)
        child = _get_child_in_establishment(child_id, establishment)
        installment = get_object_or_404(
            FeeInstallment.objects.select_related("fee_schedule__establishment"), pk=installment_id
        )
        if installment.fee_schedule.establishment_id != establishment.id:
            raise PermissionDenied("Cette tranche n'appartient pas à votre établissement.")

        amount_paid = request.data.get("amount_paid")
        try:
            amount_paid = int(amount_paid)
        except (TypeError, ValueError):
            raise ValidationError({"amount_paid": "Montant invalide."})
        if amount_paid <= 0:
            raise ValidationError({"amount_paid": "Le montant doit être positif."})

        payment = FeePayment.objects.create(
            child=child,
            fee_installment=installment,
            amount_paid=amount_paid,
            payment_channel=request.data.get("payment_channel", "cash"),
            paid_at=timezone.now(),
            recorded_by=request.user,
        )
        return Response(FeePaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class EstablishmentFeeDashboardView(APIView):
    """Tableau de bord financier de l'établissement pour une année
    scolaire : montant total attendu, montant encaissé, familles en
    retard — chiffres calculés à la volée (voir services.py)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        establishment = _get_establishment(request.user)
        school_year = request.query_params.get("school_year")
        if not school_year:
            raise ValidationError({"school_year": "Paramètre obligatoire."})

        totals = services.establishment_fee_totals(establishment, school_year)
        schedule = FeeSchedule.objects.filter(establishment=establishment, school_year=school_year).first()
        late_families = []
        if schedule:
            for entry in services.late_children_for_schedule(schedule):
                child = entry["child"]
                late_families.append({
                    "child_id": child.id,
                    "child_name": f"{child.first_name} {child.last_name}".strip(),
                    "late_installments": [s["installment"].name for s in entry["installments"] if s["status"] == "late"],
                })
        return Response({
            "total_expected": totals["total_expected"],
            "total_collected": totals["total_collected"],
            "late_families": late_families,
        })


class RemindLateFamilyView(APIView):
    """Relance rapide d'une famille en retard — réutilise le système de
    notification déjà en place, aucun canal d'envoi séparé."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, child_id):
        from apps.notifications.models import NotificationType
        from apps.notifications.services import notify_user

        establishment = _get_establishment(request.user)
        child = _get_child_in_establishment(child_id, establishment)
        if not (child.parent_id and child.parent.user_id):
            raise ValidationError("Aucun compte parent actif pour cet élève.")
        notify_user(
            child.parent.user,
            NotificationType.SYSTEM,
            title="Frais de scolarité en retard",
            body=f"Un ou plusieurs versements pour {child.first_name} sont en retard auprès de "
                 f"{establishment.school_name}.",
        )
        return Response({"detail": "Relance envoyée."})
