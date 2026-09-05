from rest_framework import serializers

from apps.grading.models import Term
from apps.users.models import Child

from .models import Exercise, ExerciseStatus, Submission, VirtualClass


class ExerciseSerializer(serializers.ModelSerializer):
    is_overdue = serializers.BooleanField(read_only=True)
    # Obligatoire à la création (voir Exercise.term) — la correction d'une
    # soumission notée en a besoin pour savoir dans quel trimestre
    # alimenter le tableur de notes. La portée réelle (établissement) est
    # vérifiée côté vue, pas ici (même convention que le reste du projet).
    term = serializers.PrimaryKeyRelatedField(queryset=Term.objects.all())

    class Meta:
        model = Exercise
        fields = [
            "id", "kind", "title", "instructions", "attachments", "deadline", "term",
            "status", "is_overdue", "published_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "is_overdue", "published_at", "created_at", "updated_at"]


class ExerciseCardSerializer(serializers.ModelSerializer):
    """Représentation légère d'un devoir pour son affichage en carte
    distincte dans un fil de messagerie (voir Message.exercise_id) — les
    consignes complètes restent sur l'écran dédié à la matière, jamais
    dupliquées ici."""

    subject_name = serializers.CharField(source="virtual_class.subject.name", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    my_submission_status = serializers.SerializerMethodField()
    my_dm_channel_id = serializers.SerializerMethodField()

    class Meta:
        model = Exercise
        fields = [
            "id", "kind", "title", "subject_name", "deadline", "status",
            "is_overdue", "attachments", "my_submission_status", "my_dm_channel_id",
        ]
        read_only_fields = fields

    def _child(self):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        return getattr(request.user, "child_profile", None)

    def get_my_submission_status(self, obj):
        child = self._child()
        if not child:
            return None
        submission = obj.submissions.filter(child=child).first()
        return submission.status if submission else None

    def get_my_dm_channel_id(self, obj):
        """DM déjà existante avec l'enseignant dédié de la matière — le tap
        sur la carte y bascule directement (jamais de réponse dans le
        canal de matière lui-même)."""
        child = self._child()
        teacher = obj.virtual_class.subject.teacher
        if not child or not teacher or not child.user_id:
            return None
        from apps.messaging.models import Channel, ChannelType

        channel = Channel.objects.filter(
            channel_type=ChannelType.DIRECT, memberships__user_id=child.user_id
        ).filter(memberships__user_id=teacher.id).first()
        return channel.id if channel else None


class SubmissionChildSerializer(serializers.ModelSerializer):
    class Meta:
        model = Child
        fields = ["id", "first_name"]
        read_only_fields = fields


class SubmissionSerializer(serializers.ModelSerializer):
    child = SubmissionChildSerializer(read_only=True)
    child_id = serializers.PrimaryKeyRelatedField(source="child", queryset=Child.objects.all(), write_only=True)
    exercise_title = serializers.CharField(source="exercise.title", read_only=True)
    is_late = serializers.BooleanField(read_only=True)

    class Meta:
        model = Submission
        fields = [
            "id", "exercise", "exercise_title", "child", "child_id", "content", "attachments",
            "status", "grade", "feedback", "is_late", "submitted_at", "updated_at", "graded_at",
        ]
        read_only_fields = [
            "id", "exercise", "exercise_title", "status", "grade", "feedback",
            "is_late", "submitted_at", "updated_at", "graded_at",
        ]


class SubmissionEditSerializer(serializers.ModelSerializer):
    """Modification de sa propre copie, réservée à l'élève/parent auteur,
    et seulement avant l'échéance — voir SubmissionDetailView."""

    class Meta:
        model = Submission
        fields = ["content", "attachments"]


class SubmissionGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = ["grade", "feedback"]

    def validate_grade(self, value):
        if value is not None and not (0 <= value <= 20):
            raise serializers.ValidationError("La note doit être comprise entre 0 et 20.")
        return value


class ChildExerciseSerializer(serializers.ModelSerializer):
    my_submission = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)
    my_dm_channel_id = serializers.SerializerMethodField()

    class Meta:
        model = Exercise
        fields = [
            "id", "kind", "title", "instructions", "attachments", "deadline",
            "status", "is_overdue", "published_at", "my_submission", "my_dm_channel_id",
        ]
        read_only_fields = fields

    def get_my_submission(self, obj):
        child = self.context["child"]
        submission = obj.submissions.filter(child=child).first()
        return SubmissionSerializer(submission).data if submission else None

    def get_my_dm_channel_id(self, obj):
        """DM déjà existante avec l'enseignant dédié — pour basculer
        directement dessus depuis « Mes devoirs », jamais de réponse dans
        le canal de matière."""
        child = self.context["child"]
        teacher = obj.virtual_class.subject.teacher
        if not child.user_id or not teacher:
            return None
        from apps.messaging.models import Channel, ChannelType

        channel = Channel.objects.filter(
            channel_type=ChannelType.DIRECT, memberships__user_id=child.user_id
        ).filter(memberships__user_id=teacher.id).first()
        return channel.id if channel else None


class ChildSubjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    school_class_name = serializers.CharField(source="school_class.name")
    exercises = serializers.SerializerMethodField()

    def get_exercises(self, obj):
        child = self.context["child"]
        virtual_class = getattr(obj, "virtual_class", None)
        if not virtual_class:
            return []
        # PUBLIÉ et CLÔTURÉ tous deux visibles ici — un devoir clôturé
        # (marqué "corrigé" par l'enseignant) doit continuer à apparaître
        # chez l'élève avec sa note, jamais disparaître. Seul un brouillon
        # (jamais publié) reste invisible côté élève.
        exercises = virtual_class.exercises.filter(
            status__in=[ExerciseStatus.PUBLISHED, ExerciseStatus.CLOSED]
        )
        return ChildExerciseSerializer(exercises, many=True, context={"child": child}).data


class VirtualClassSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    school_class_name = serializers.CharField(source="subject.school_class.name", read_only=True)
    exercise_count = serializers.SerializerMethodField()

    class Meta:
        model = VirtualClass
        fields = [
            "id", "subject", "subject_name", "school_class_name",
            "description", "is_active", "exercise_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "subject", "created_at", "updated_at"]

    def get_exercise_count(self, obj):
        return obj.exercises.count()
