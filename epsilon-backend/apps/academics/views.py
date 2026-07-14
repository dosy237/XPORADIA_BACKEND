from rest_framework import generics, permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from apps.users.models import DirectorProfile, UserRole

from .models import Department, SchoolClass, Track
from .serializers import DepartmentSerializer, SchoolClassSerializer, TrackSerializer


def _require_director(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")


def _director_establishment(user):
    try:
        return user.director_profile
    except DirectorProfile.DoesNotExist:
        raise PermissionDenied("Aucun établissement associé à ce compte.")


class DepartmentViewSet(viewsets.ModelViewSet):
    """CRUD des départements de l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DepartmentSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return Department.objects.filter(establishment__user=self.request.user)

    def perform_create(self, serializer):
        establishment = _director_establishment(self.request.user)
        serializer.save(establishment=establishment)


class TrackViewSet(viewsets.ModelViewSet):
    """CRUD des filières — chaque filière appartient à un département de
    l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TrackSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return Track.objects.filter(department__establishment__user=self.request.user)

    def perform_create(self, serializer):
        department = serializer.validated_data["department"]
        if department.establishment.user_id != self.request.user.id:
            raise PermissionDenied("Ce département n'appartient pas à votre établissement.")
        serializer.save()


class SchoolClassViewSet(viewsets.ModelViewSet):
    """CRUD des classes — chaque classe appartient à une filière de
    l'établissement du directeur connecté, avec affectation de
    l'enseignant titulaire."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SchoolClassSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return SchoolClass.objects.filter(
            track__department__establishment__user=self.request.user
        ).select_related("track", "homeroom_teacher")

    def _validate_track_ownership(self, serializer):
        track = serializer.validated_data.get("track")
        if track and track.department.establishment.user_id != self.request.user.id:
            raise PermissionDenied("Cette filière n'appartient pas à votre établissement.")

    def perform_create(self, serializer):
        self._validate_track_ownership(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._validate_track_ownership(serializer)
        serializer.save()


class MyHomeroomClassesView(generics.ListAPIView):
    """Classes dont l'enseignant connecté est titulaire."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SchoolClassSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return SchoolClass.objects.filter(
            homeroom_teacher=self.request.user, is_active=True
        ).select_related("track", "track__department")
