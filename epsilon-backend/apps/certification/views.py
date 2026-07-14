from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import UserRole

from .models import TrainingModule, TrainingSession
from .serializers import (
    MyCertificationStatusSerializer,
    TrainingModuleSerializer,
    TrainingSessionSerializer,
)


class TrainingModuleViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalogue public des modules de formation (lecture seule)."""

    permission_classes = [permissions.IsAuthenticated]
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
    """Sessions de formation à venir, filtrables par module et ville."""

    permission_classes = [permissions.IsAuthenticated]
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
