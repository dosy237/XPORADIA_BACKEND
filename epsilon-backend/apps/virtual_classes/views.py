from django.http import Http404
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response

from apps.academics.models import Enrollment, EnrollmentStatus, Subject
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import Child

from .models import Exercise, ExerciseStatus, Submission, SubmissionStatus, VirtualClass
from .serializers import (
    ChildSubjectSerializer,
    ExerciseSerializer,
    SubmissionGradeSerializer,
    SubmissionSerializer,
    VirtualClassSerializer,
)


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


def _notify_enrolled_parents(school_class, notif_type, title, body):
    notified_parent_ids = set()
    enrollments = Enrollment.objects.filter(
        school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).select_related("child__parent__user")
    for enrollment in enrollments:
        parent_user = enrollment.child.parent.user
        if parent_user.id in notified_parent_ids:
            continue
        notified_parent_ids.add(parent_user.id)
        notify_user(parent_user, notif_type, title=title, body=body)


def _get_own_child(child_id, user):
    try:
        child = Child.objects.select_related("parent__user").get(id=child_id)
    except Child.DoesNotExist:
        raise Http404
    if child.parent.user_id != user.id:
        raise PermissionDenied("Cet enfant n'est pas rattaché à votre compte.")
    return child


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
            _notify_enrolled_parents(
                subject.school_class,
                NotificationType.EXERCISE_PUBLISHED,
                title="Nouveau devoir publié",
                body=f"« {exercise.title} » a été publié pour la matière {subject.name}.",
            )


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
            _notify_enrolled_parents(
                subject.school_class,
                NotificationType.EXERCISE_PUBLISHED,
                title="Nouveau devoir publié",
                body=f"« {exercise.title} » a été publié pour la matière {subject.name}.",
            )

    def perform_destroy(self, instance):
        subject = instance.virtual_class.subject
        if not _can_manage(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        instance.delete()


class ChildSubjectsView(APIView):
    """Espace élève côté parent — matières de la classe où l'enfant est
    inscrit, avec les devoirs publiés et l'état de soumission de l'enfant
    pour chacun. Accès médié par le parent : pas de compte élève propre."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, child_id):
        child = _get_own_child(child_id, request.user)
        enrollment = (
            Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
            .select_related("school_class")
            .first()
        )
        if not enrollment:
            return Response([])
        subjects = Subject.objects.filter(school_class=enrollment.school_class).select_related("school_class")
        return Response(ChildSubjectSerializer(subjects, many=True, context={"child": child}).data)


class ExerciseSubmissionsView(generics.ListCreateAPIView):
    """Soumissions d'un devoir — le parent soumet au nom de son enfant,
    l'enseignant dédié consulte les copies reçues."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubmissionSerializer
    pagination_class = None

    def _get_exercise(self):
        try:
            return Exercise.objects.select_related(
                "virtual_class__subject__teacher", "virtual_class__subject__school_class"
            ).get(id=self.kwargs["exercise_id"])
        except Exercise.DoesNotExist:
            raise Http404

    def get_queryset(self):
        exercise = self._get_exercise()
        subject = exercise.virtual_class.subject
        if not _can_view(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié ou au titulaire de cette classe.")
        return Submission.objects.filter(exercise=exercise).select_related("child")

    def perform_create(self, serializer):
        exercise = self._get_exercise()
        if exercise.status != ExerciseStatus.PUBLISHED:
            raise PermissionDenied("Ce devoir n'est pas encore publié.")
        child = serializer.validated_data["child"]
        if child.parent.user_id != self.request.user.id:
            raise PermissionDenied("Cet enfant n'est pas rattaché à votre compte.")
        subject = exercise.virtual_class.subject
        is_enrolled = Enrollment.objects.filter(
            child=child, school_class=subject.school_class, status=EnrollmentStatus.ACTIVE
        ).exists()
        if not is_enrolled:
            raise PermissionDenied("Cet enfant n'est pas inscrit dans la classe de ce devoir.")
        if Submission.objects.filter(exercise=exercise, child=child).exists():
            raise ValidationError("Une copie a déjà été soumise pour ce devoir.")
        serializer.save(exercise=exercise, submitted_by=self.request.user)
        if subject.teacher:
            notify_user(
                subject.teacher,
                NotificationType.EXERCISE_SUBMITTED,
                title="Nouvelle copie soumise",
                body=f"{child.first_name} a soumis une copie pour « {exercise.title} ».",
            )


class SubmissionDetailView(generics.RetrieveUpdateAPIView):
    """Détail d'une soumission — consultable par l'enseignant dédié et le
    parent de l'élève concerné ; notable par l'enseignant dédié uniquement."""

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return SubmissionGradeSerializer
        return SubmissionSerializer

    def get_queryset(self):
        return Submission.objects.select_related(
            "exercise__virtual_class__subject__teacher", "child__parent__user"
        )

    def get_object(self):
        submission = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        subject = submission.exercise.virtual_class.subject
        user = self.request.user
        is_teacher = _can_manage(subject, user)
        is_parent = submission.child.parent.user_id == user.id
        if not (is_teacher or is_parent):
            raise PermissionDenied("Accès réservé à l'enseignant dédié ou au parent de l'élève concerné.")
        return submission

    def perform_update(self, serializer):
        submission = serializer.instance
        subject = submission.exercise.virtual_class.subject
        if not _can_manage(subject, self.request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        submission = serializer.save(
            status=SubmissionStatus.GRADED, graded_by=self.request.user, graded_at=timezone.now()
        )
        notify_user(
            submission.submitted_by,
            NotificationType.CORRECTION_READY,
            title="Correction disponible",
            body=f"La copie de {submission.child.first_name} pour « {submission.exercise.title} » a été corrigée.",
        )


class MySubmissionsView(generics.ListAPIView):
    """Suivi, côté parent, des copies soumises au nom de ses enfants."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubmissionSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Submission.objects.filter(submitted_by=self.request.user)
            .select_related("exercise", "child")
            .order_by("-submitted_at")
        )
