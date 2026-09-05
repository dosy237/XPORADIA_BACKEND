from django.http import Http404
from django.utils import timezone
from rest_framework import filters, generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response

from apps.academics.models import Enrollment, EnrollmentStatus, SchoolClass, Subject
from apps.grading.models import Evaluation, EvaluationType
from apps.grading.views import _save_grade
from apps.messaging.services import save_uploaded_attachments
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import Child, UserRole

from .models import Exercise, ExerciseKind, ExerciseStatus, Submission, SubmissionStatus, VirtualClass
from .serializers import (
    ChildSubjectSerializer,
    ExerciseSerializer,
    SubmissionEditSerializer,
    SubmissionGradeSerializer,
    SubmissionSerializer,
    VirtualClassSerializer,
)
from .services import notify_enrolled_parents as _notify_enrolled_parents


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


def _get_own_child(child_id, user):
    try:
        child = Child.objects.select_related("parent__user").get(id=child_id)
    except Child.DoesNotExist:
        raise Http404
    if not (child.parent_id and child.parent.user_id == user.id):
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
        term = serializer.validated_data.get("term")
        establishment = subject.school_class.track.department.establishment
        if term and term.establishment_id != establishment.id:
            raise ValidationError({"term": "Ce trimestre n'appartient pas à cet établissement."})
        exercise = serializer.save(virtual_class=virtual_class)
        files = self.request.FILES.getlist("attachments")
        if files:
            exercise.attachments = save_uploaded_attachments(files, self.request, upload_to="exercise_attachments")
            exercise.save(update_fields=["attachments"])
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
    """Soumissions d'un devoir — l'élève soumet lui-même s'il a activé son
    compte, sinon son parent soumet en son nom ; l'enseignant dédié
    consulte, trie et recherche parmi les copies reçues."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubmissionSerializer
    pagination_class = None
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["child__first_name", "child__last_name"]
    ordering_fields = ["submitted_at", "grade", "status"]

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
            raise PermissionDenied("Ce devoir n'accepte plus de nouvelle soumission.")
        child = serializer.validated_data["child"]
        user = self.request.user
        # L'élève soumet pour lui-même (compte activé), ou un parent soumet
        # au nom de son enfant — les deux voies restent ouvertes tant que
        # tous les élèves n'ont pas de compte propre.
        is_self = child.user_id == user.id
        is_parent = bool(child.parent_id) and child.parent.user_id == user.id
        if not (is_self or is_parent):
            raise PermissionDenied("Cet élève ne vous est pas rattaché.")
        subject = exercise.virtual_class.subject
        is_enrolled = Enrollment.objects.filter(
            child=child, school_class=subject.school_class, status=EnrollmentStatus.ACTIVE
        ).exists()
        if not is_enrolled:
            raise PermissionDenied("Cet élève n'est pas inscrit dans la classe de ce devoir.")
        if Submission.objects.filter(exercise=exercise, child=child).exists():
            raise ValidationError("Une copie a déjà été soumise pour ce devoir.")
        serializer.save(exercise=exercise, submitted_by=user)
        if subject.teacher:
            notify_user(
                subject.teacher,
                NotificationType.EXERCISE_SUBMITTED,
                title="Nouvelle copie soumise",
                body=f"{child.first_name} a soumis une copie pour « {exercise.title} ».",
            )


class ExerciseSubmissionStatsView(APIView):
    """Bandeau de stats pour l'enseignant qui corrige — combien de rendus,
    en retard, et non-rendus (calculé sur l'effectif inscrit)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, exercise_id):
        try:
            exercise = Exercise.objects.select_related("virtual_class__subject__school_class").get(
                id=exercise_id
            )
        except Exercise.DoesNotExist:
            raise Http404
        subject = exercise.virtual_class.subject
        if not _can_view(subject, request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié ou au titulaire de cette classe.")

        total_enrolled = Enrollment.objects.filter(
            school_class=subject.school_class, status=EnrollmentStatus.ACTIVE
        ).count()
        submissions = Submission.objects.filter(exercise=exercise)
        submitted_count = submissions.count()
        late_count = sum(1 for s in submissions if s.is_late)
        graded_count = submissions.filter(status=SubmissionStatus.GRADED).count()

        return Response(
            {
                "total_enrolled": total_enrolled,
                "submitted_count": submitted_count,
                "not_submitted_count": max(total_enrolled - submitted_count, 0),
                "late_count": late_count,
                "graded_count": graded_count,
            }
        )


class ExerciseStudentStatusView(APIView):
    """Effectif complet de la classe pour un devoir, avec le statut
    individuel de chacun (pas soumis / soumis / corrigé) — contrairement à
    ExerciseSubmissionsView qui ne renvoie que les copies déjà rendues, ici
    chaque élève inscrit apparaît, y compris ceux n'ayant pas encore
    soumis. Le tap sur un élève ayant soumis bascule vers la DM existante
    avec lui (channel_id renvoyé quand elle existe déjà)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, exercise_id):
        from apps.messaging.models import Channel, ChannelType

        try:
            exercise = Exercise.objects.select_related("virtual_class__subject__school_class").get(
                id=exercise_id
            )
        except Exercise.DoesNotExist:
            raise Http404
        subject = exercise.virtual_class.subject
        if not _can_view(subject, request.user):
            raise PermissionDenied("Réservé à l'enseignant dédié ou au titulaire de cette classe.")

        enrollments = Enrollment.objects.filter(
            school_class=subject.school_class, status=EnrollmentStatus.ACTIVE
        ).select_related("child__user").order_by("child__first_name")
        submissions_by_child = {s.child_id: s for s in Submission.objects.filter(exercise=exercise)}

        results = []
        for enrollment in enrollments:
            child = enrollment.child
            submission = submissions_by_child.get(child.id)
            channel_id = None
            if child.user_id and subject.teacher_id:
                channel = Channel.objects.filter(
                    channel_type=ChannelType.DIRECT, memberships__user_id=subject.teacher_id
                ).filter(memberships__user_id=child.user_id).first()
                channel_id = channel.id if channel else None
            results.append({
                "child_id": child.id,
                "first_name": child.first_name,
                "last_name": child.last_name,
                "avatar": (
                    request.build_absolute_uri(child.user.avatar.url)
                    if child.user_id and child.user.avatar else None
                ),
                "status": submission.status if submission else "not_submitted",
                "submission_id": submission.id if submission else None,
                "grade": str(submission.grade) if submission and submission.grade is not None else None,
                "channel_id": channel_id,
            })
        return Response(results)


class HomeroomExercisesOverviewView(APIView):
    """Vue consolidée pour le professeur principal : tous les devoirs de
    toutes les matières de sa classe, avec leurs stats de rendu — pour ne
    jamais avoir à rouvrir chaque matière une par une pour savoir qui a
    rendu quoi. Réservée au titulaire (ou au directeur de l'établissement)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, class_id):
        try:
            school_class = SchoolClass.objects.select_related(
                "homeroom_teacher", "track__department__establishment"
            ).get(id=class_id)
        except SchoolClass.DoesNotExist:
            raise Http404

        is_homeroom = school_class.homeroom_teacher_id == request.user.id
        is_director = (
            request.user.has_role(UserRole.DIRECTOR)
            and school_class.track.department.establishment.user_id == request.user.id
        )
        if not (is_homeroom or is_director):
            raise PermissionDenied("Réservé au titulaire de cette classe ou au directeur de l'établissement.")

        total_enrolled = Enrollment.objects.filter(
            school_class=school_class, status=EnrollmentStatus.ACTIVE
        ).count()

        exercises = (
            Exercise.objects.filter(virtual_class__subject__school_class=school_class)
            .select_related("virtual_class__subject")
            .prefetch_related("submissions")
            .order_by("virtual_class__subject__name", "-created_at")
        )

        overview = {}
        for exercise in exercises:
            subject_name = exercise.virtual_class.subject.name
            submissions = list(exercise.submissions.all())
            submitted_count = len(submissions)
            entry = {
                "id": str(exercise.id),
                "kind": exercise.kind,
                "title": exercise.title,
                "status": exercise.status,
                "deadline": exercise.deadline,
                "total_enrolled": total_enrolled,
                "submitted_count": submitted_count,
                "not_submitted_count": max(total_enrolled - submitted_count, 0),
                "late_count": sum(1 for s in submissions if s.is_late),
                "graded_count": sum(1 for s in submissions if s.status == SubmissionStatus.GRADED),
            }
            overview.setdefault(subject_name, []).append(entry)

        return Response(overview)


class MyGradingQueueView(APIView):
    """Vue agrégée pour le dashboard enseignant : combien de copies
    attendent une correction, toutes matières dédiées confondues — pour
    ne pas avoir à ouvrir chaque matière une par une pour le savoir."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")

        exercises = (
            Exercise.objects.filter(virtual_class__subject__teacher=request.user, status=ExerciseStatus.PUBLISHED)
            .select_related("virtual_class__subject")
            .prefetch_related("submissions")
            .order_by("created_at")
        )

        queue = []
        total_pending = 0
        for exercise in exercises:
            pending = sum(1 for s in exercise.submissions.all() if s.status != SubmissionStatus.GRADED)
            if pending > 0:
                total_pending += pending
                queue.append({
                    "exercise_id": str(exercise.id),
                    "title": exercise.title,
                    "subject_name": exercise.virtual_class.subject.name,
                    "pending_count": pending,
                })

        return Response({"total_pending": total_pending, "exercises": queue[:5]})


def _sync_grading_column(submission, teacher):
    """Une correction notée dans "Ma classe" doit se refléter dans le
    tableur de notes officiel — jusqu'ici Exercise/Submission et
    Evaluation/Grade étaient deux systèmes complètement séparés : noter
    un devoir n'avait aucun effet sur la moyenne ni le bulletin. La
    colonne (Evaluation) est créée à la première note réelle, jamais à
    la création du devoir (pas de colonne vide avant toute correction),
    et seulement si un trimestre a été renseigné (voir Exercise.term —
    nullable pour les devoirs créés avant l'ajout de ce champ)."""
    exercise = submission.exercise
    if submission.grade is None or exercise.term_id is None:
        return
    if exercise.evaluation_id is None:
        eval_type = EvaluationType.EXAM if exercise.kind == ExerciseKind.EXAM else EvaluationType.HOMEWORK
        evaluation = Evaluation.objects.create(
            subject=exercise.virtual_class.subject,
            term=exercise.term,
            title=exercise.title,
            eval_type=eval_type,
            max_score=20,
            date=exercise.deadline.date() if exercise.deadline else timezone.localdate(),
            created_by=teacher,
        )
        exercise.evaluation = evaluation
        exercise.save(update_fields=["evaluation"])
    _save_grade(exercise.evaluation, submission.child_id, submission.grade, False, teacher)


class SubmissionDetailView(generics.RetrieveUpdateAPIView):
    """Détail d'une soumission — consultable par l'enseignant dédié et
    l'élève/parent concerné. Deux chemins d'écriture bien distincts :
    l'élève/parent peut modifier le CONTENU jusqu'à l'échéance (pas après),
    l'enseignant dédié peut uniquement NOTER (jamais modifier la copie)."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.select_related(
            "exercise__virtual_class__subject__teacher", "child__parent__user", "child__user"
        )

    def _is_owner(self, submission, user):
        child = submission.child
        return child.user_id == user.id or (bool(child.parent_id) and child.parent.user_id == user.id)

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            submission = self.get_object()
            if self._is_owner(submission, self.request.user):
                return SubmissionEditSerializer
            return SubmissionGradeSerializer
        return SubmissionSerializer

    def get_object(self):
        submission = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        subject = submission.exercise.virtual_class.subject
        user = self.request.user
        is_teacher = _can_manage(subject, user)
        if not (is_teacher or self._is_owner(submission, user)):
            raise PermissionDenied("Accès réservé à l'enseignant dédié ou à l'élève concerné.")
        return submission

    def perform_update(self, serializer):
        submission = serializer.instance
        subject = submission.exercise.virtual_class.subject
        user = self.request.user

        if self._is_owner(submission, user):
            # Modification du contenu — fermée dès que l'échéance est
            # passée (même règle que pour un premier dépôt tardif : après
            # la deadline, on peut encore RENDRE mais plus MODIFIER) et dès
            # que l'enseignant a fermé le devoir à la correction.
            exercise = submission.exercise
            if exercise.status != ExerciseStatus.PUBLISHED:
                raise PermissionDenied("Ce devoir n'accepte plus de modification (correction en cours).")
            if exercise.deadline and timezone.now() > exercise.deadline:
                raise PermissionDenied("La date limite est passée — la copie ne peut plus être modifiée.")
            serializer.save()
            return

        if not _can_manage(subject, user):
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        submission = serializer.save(
            status=SubmissionStatus.GRADED, graded_by=user, graded_at=timezone.now()
        )
        _sync_grading_column(submission, user)
        notify_user(
            submission.submitted_by,
            NotificationType.CORRECTION_READY,
            title="Correction disponible",
            body=f"La copie de {submission.child.first_name} pour « {submission.exercise.title} » a été corrigée.",
        )
        self._post_grading_message(submission, user)

    def _post_grading_message(self, submission, teacher):
        """Reflète la correction comme un message dans la DM élève/
        enseignant, au même titre qu'une soumission — seulement possible si
        l'élève a un compte activé (pas de DM sans compte destinataire)."""
        child = submission.child
        if not child.user_id:
            return

        from apps.messaging.models import Message
        from apps.messaging.realtime import broadcast_to_channel
        from apps.messaging.serializers import MessageSerializer
        from apps.messaging.services import get_or_create_direct_channel

        channel = get_or_create_direct_channel(teacher, child.user)
        grade_text = f"{submission.grade}/20" if submission.grade is not None else "Non noté"
        body = f"Correction : {grade_text}"
        if submission.feedback:
            body += f"\n{submission.feedback}"
        message = Message.objects.create(
            channel=channel, author=teacher, body=body, exercise_id=submission.exercise_id
        )
        broadcast_to_channel(
            channel.id, "message_created",
            {"message": MessageSerializer(message, context={"request": self.request}).data},
        )


class MySubmissionsView(generics.ListAPIView):
    """Suivi de ses propres copies rendues — élève (compte activé) ou
    parent en son nom. Montre tout l'historique de l'élève, y compris les
    copies rendues par le parent avant que le compte élève n'existe."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubmissionSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "child_profile"):
            return (
                Submission.objects.filter(child=user.child_profile)
                .select_related("exercise", "child")
                .order_by("-submitted_at")
            )
        return (
            Submission.objects.filter(submitted_by=user)
            .select_related("exercise", "child")
            .order_by("-submitted_at")
        )


class MySubjectsView(APIView):
    """Espace élève — matières de sa classe, avec les devoirs publiés et
    l'état de sa propre soumission pour chacun. Réservé aux comptes élève
    activés (voir ChildSubjectsView pour l'équivalent côté parent)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        enrollment = (
            Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
            .select_related("school_class")
            .first()
        )
        if not enrollment:
            return Response([])
        subjects = Subject.objects.filter(school_class=enrollment.school_class).select_related("school_class")
        return Response(ChildSubjectSerializer(subjects, many=True, context={"child": child}).data)
