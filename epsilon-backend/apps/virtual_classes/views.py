from django.http import Http404
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied

from apps.academics.models import Subject

from .models import Exercise, ExerciseStatus, VirtualClass
from .serializers import ExerciseSerializer, VirtualClassSerializer


def _get_subject(subject_id):
    try:
        return Subject.objects.select_related(
            "teacher", "school_class", "school_class__homeroom_teacher"
        ).get(id=subject_id)
    except Subject.DoesNotExist:
        raise Http404


def _can_manage(subject, user):
    return subject.teacher_id == user.id


def _can_view(subject, user):
    return subject.teacher_id == user.id or subject.school_class.homeroom_teacher_id == user.id


class SubjectVirtualClassView(generics.RetrieveUpdateAPIView):
    """Espace numérique (cours/exercices) d'une matière — visible par
    l'enseignant dédié et le titulaire de la classe, modifiable par
    l'enseignant dédié uniquement."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = VirtualClassSerializer

    def get_object(self):
        subject = _get_subject(self.kwargs["subject_id"])
        if not _can_view(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié ou au titulaire de cette classe.")
        virtual_class, _ = VirtualClass.objects.get_or_create(subject=subject)
        return virtual_class

    def perform_update(self, serializer):
        subject = serializer.instance.subject
        if not _can_manage(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        serializer.save()


class ExerciseListCreateView(generics.ListCreateAPIView):
    """Cours/exercices d'une matière — créés et gérés par l'enseignant
    dédié, visibles aussi par le titulaire de la classe."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ExerciseSerializer
    pagination_class = None

    def _get_virtual_class(self):
        subject = _get_subject(self.kwargs["subject_id"])
        if not _can_view(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié ou au titulaire de cette classe.")
        virtual_class, _ = VirtualClass.objects.get_or_create(subject=subject)
        return virtual_class, subject

    def get_queryset(self):
        virtual_class, _ = self._get_virtual_class()
        return Exercise.objects.filter(virtual_class=virtual_class)

    def perform_create(self, serializer):
        virtual_class, subject = self._get_virtual_class()
        if not _can_manage(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        exercise = serializer.save(virtual_class=virtual_class)
        if exercise.status == ExerciseStatus.PUBLISHED and not exercise.published_at:
            exercise.published_at = timezone.now()
            exercise.save(update_fields=["published_at"])


class ExerciseDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Détail d'un cours/exercice — réservé à l'enseignant dédié (écriture)
    et au titulaire de la classe (lecture)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ExerciseSerializer

    def get_queryset(self):
        return Exercise.objects.select_related(
            "virtual_class__subject__teacher",
            "virtual_class__subject__school_class__homeroom_teacher",
        )

    def get_object(self):
        exercise = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        subject = exercise.virtual_class.subject
        if not _can_view(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié ou au titulaire de cette classe.")
        return exercise

    def perform_update(self, serializer):
        exercise = serializer.instance
        subject = exercise.virtual_class.subject
        if not _can_manage(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        was_published = exercise.status == ExerciseStatus.PUBLISHED
        exercise = serializer.save()
        if exercise.status == ExerciseStatus.PUBLISHED and not was_published and not exercise.published_at:
            exercise.published_at = timezone.now()
            exercise.save(update_fields=["published_at"])

    def perform_destroy(self, instance):
        subject = instance.virtual_class.subject
        if not _can_manage(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        instance.delete()
