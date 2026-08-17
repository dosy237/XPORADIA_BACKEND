from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import User, UserRole

from .models import Dispute, DisputeStatus, Payment
from .serializers import DisputeSerializer, PaymentSerializer


class MyPaymentsView(generics.ListAPIView):
    """Historique des paiements Mobile Money de l'utilisateur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PaymentSerializer
    pagination_class = None

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user).order_by("-created_at")


class OpenDisputeView(APIView):
    """N'importe quel utilisateur peut contester UN DE SES PROPRES
    paiements — jamais celui d'un tiers. Notifie tous les administrateurs,
    qui traitent la file (voir AdminDisputesView)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, payment_id):
        payment = get_object_or_404(Payment, pk=payment_id, user=request.user)
        reason = request.data.get("reason", "").strip()
        if not reason:
            raise ValidationError({"reason": "Un motif est requis."})
        if Dispute.objects.filter(payment=payment, status__in=[DisputeStatus.OPEN, DisputeStatus.REVIEWED]).exists():
            return Response({"detail": "Un litige est déjà ouvert pour ce paiement."}, status=400)

        dispute = Dispute.objects.create(payment=payment, opened_by=request.user, reason=reason)
        for admin in User.objects.filter(primary_role=UserRole.ADMIN, is_active=True):
            notify_user(
                admin, NotificationType.SYSTEM,
                title="Nouveau litige de paiement",
                body=f"{request.user.get_full_name()} conteste un paiement de {payment.amount} FCFA.",
                data={"dispute_id": dispute.id},
            )
        return Response(DisputeSerializer(dispute).data, status=201)


class AdminDisputesView(generics.ListAPIView):
    """File des litiges — réservée aux administrateurs."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DisputeSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.ADMIN):
            raise PermissionDenied("Réservé aux administrateurs.")
        status_filter = self.request.query_params.get("status")
        qs = Dispute.objects.select_related("payment", "opened_by").order_by("-created_at")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class ResolveDisputeView(APIView):
    """Résolution d'un litige par un administrateur — notifie la
    personne qui l'avait ouvert."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not request.user.has_role(UserRole.ADMIN):
            raise PermissionDenied("Réservé aux administrateurs.")
        dispute = get_object_or_404(Dispute, pk=pk)
        if dispute.status in (DisputeStatus.RESOLVED, DisputeStatus.CLOSED):
            return Response({"detail": "Ce litige est déjà clos."}, status=400)

        new_status = request.data.get("status")
        if new_status not in (DisputeStatus.RESOLVED, DisputeStatus.CLOSED):
            raise ValidationError({"status": "Doit être 'resolved' ou 'closed'."})

        dispute.status = new_status
        dispute.resolution = request.data.get("resolution", "")
        dispute.resolved_by = request.user
        dispute.resolved_at = timezone.now()
        dispute.save(update_fields=["status", "resolution", "resolved_by", "resolved_at"])

        notify_user(
            dispute.opened_by, NotificationType.SYSTEM,
            title="Votre litige a été traité",
            body=f"Statut : {dispute.get_status_display()}."
                 + (f" {dispute.resolution}" if dispute.resolution else ""),
        )
        return Response(DisputeSerializer(dispute).data)
