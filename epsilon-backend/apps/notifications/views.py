from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeviceToken, Notification, NotificationCategory, NotificationPreference
from .serializers import (
    NotificationPreferenceEntrySerializer,
    NotificationSerializer,
    RegisterDeviceTokenSerializer,
    UnregisterDeviceTokenSerializer,
    UpdateNotificationPreferenceSerializer,
)


class NotificationListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer
    pagination_class = None  # volume par utilisateur toujours modeste

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class MarkNotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        notification = generics.get_object_or_404(
            Notification, pk=pk, user=request.user
        )
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return Response(NotificationSerializer(notification).data)


class RegisterDeviceTokenView(APIView):
    """Enregistre (ou réassigne) le token push Expo de l'appareil courant."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = RegisterDeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DeviceToken.objects.update_or_create(
            token=serializer.validated_data["token"],
            defaults={"user": request.user, "platform": serializer.validated_data["platform"]},
        )
        return Response({"detail": "Appareil enregistré pour les notifications push."})


class MyNotificationPreferencesView(APIView):
    """État (activé/désactivé) des 4 grandes catégories de notification
    pour l'utilisateur connecté, et modification d'une catégorie. Une
    catégorie sans ligne en base est activée par défaut — voir
    NotificationPreference."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        disabled = set(
            NotificationPreference.objects.filter(user=request.user, enabled=False).values_list(
                "category", flat=True
            )
        )
        data = [
            {"category": category, "category_label": label, "enabled": category not in disabled}
            for category, label in NotificationCategory.choices
        ]
        return Response(NotificationPreferenceEntrySerializer(data, many=True).data)

    def post(self, request):
        serializer = UpdateNotificationPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = serializer.validated_data["category"]
        enabled = serializer.validated_data["enabled"]
        if enabled:
            NotificationPreference.objects.filter(user=request.user, category=category).delete()
        else:
            NotificationPreference.objects.update_or_create(
                user=request.user, category=category, defaults={"enabled": False}
            )
        return self.get(request)


class UnregisterDeviceTokenView(APIView):
    """Supprime le token à la déconnexion (l'appareil ne doit plus recevoir
    de push pour ce compte une fois l'utilisateur déconnecté)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = UnregisterDeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DeviceToken.objects.filter(
            token=serializer.validated_data["token"], user=request.user
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
