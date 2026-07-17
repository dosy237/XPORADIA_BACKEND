from rest_framework import generics, permissions

from .models import Payment
from .serializers import PaymentSerializer


class MyPaymentsView(generics.ListAPIView):
    """Historique des paiements Mobile Money de l'utilisateur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PaymentSerializer
    pagination_class = None

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user).order_by("-created_at")
