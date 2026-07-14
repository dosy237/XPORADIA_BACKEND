from django.http import Http404
from rest_framework import generics, permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import DirectorProfile, UserRole

from .models import Department, SchoolClass, Subject, Track
from .serializers import DepartmentSerializer, SchoolClassSerializer, SubjectSerializer, TrackSerializer


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


def _get_school_class(class_id):
    try:
        return SchoolClass.objects.select_related(
            "track", "track__department", "homeroom_teacher"
        ).get(id=class_id)
    except SchoolClass.DoesNotExist:
        raise Http404


def _require_homeroom_teacher(school_class, user):
    if school_class.homeroom_teacher_id != user.id:
        raise PermissionDenied("Réservé à l'enseignant titulaire de cette classe.")


def _notify_dedicated_teacher(subject):
    notify_user(
        subject.teacher,
        NotificationType.CLASS_ASSIGNMENT,
        title="Vous avez été affecté(e) à une matière",
        body=(
            f"{subject.school_class.homeroom_teacher.get_full_name()} vous a ajouté(e) comme "
            f"enseignant(e) dédié(e) sur \"{subject.name}\" ({subject.school_class})."
        ),
        data={"subject_id": subject.id, "school_class_id": subject.school_class_id},
    )


class SubjectListCreateView(generics.ListCreateAPIView):
    """Matières d'une classe — créées et gérées par l'enseignant titulaire,
    qui y affecte (ou retire) un enseignant dédié."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubjectSerializer
    pagination_class = None

    def get_queryset(self):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_homeroom_teacher(school_class, self.request.user)
        return Subject.objects.filter(school_class=school_class).select_related("teacher")

    def perform_create(self, serializer):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_homeroom_teacher(school_class, self.request.user)
        subject = serializer.save(school_class=school_class)
        if subject.teacher_id:
            _notify_dedicated_teacher(subject)


class SubjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Détail d'une matière — réservé à l'enseignant titulaire de la classe
    à laquelle elle appartient."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubjectSerializer

    def get_queryset(self):
        return Subject.objects.filter(
            school_class__homeroom_teacher=self.request.user
        ).select_related("teacher", "school_class", "school_class__track", "school_class__homeroom_teacher")

    def perform_update(self, serializer):
        previous_teacher_id = serializer.instance.teacher_id
        subject = serializer.save()
        if subject.teacher_id and subject.teacher_id != previous_teacher_id:
            _notify_dedicated_teacher(subject)


class MyDedicatedSubjectsView(generics.ListAPIView):
    """Matières où l'enseignant connecté est l'enseignant dédié."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubjectSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return Subject.objects.filter(teacher=self.request.user).select_related(
            "school_class", "school_class__track", "school_class__track__department"
        )
