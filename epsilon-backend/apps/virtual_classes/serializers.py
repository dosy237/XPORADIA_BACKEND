from rest_framework import serializers

from apps.users.models import Child

from .models import Exercise, ExerciseStatus, Submission, VirtualClass


class ExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercise
        fields = [
            "id", "title", "instructions", "attachments", "deadline",
            "status", "published_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "published_at", "created_at", "updated_at"]


class SubmissionChildSerializer(serializers.ModelSerializer):
    class Meta:
        model = Child
        fields = ["id", "first_name"]
        read_only_fields = fields


class SubmissionSerializer(serializers.ModelSerializer):
    child = SubmissionChildSerializer(read_only=True)
    child_id = serializers.PrimaryKeyRelatedField(source="child", queryset=Child.objects.all(), write_only=True)
    exercise_title = serializers.CharField(source="exercise.title", read_only=True)

    class Meta:
        model = Submission
        fields = [
            "id", "exercise", "exercise_title", "child", "child_id", "content", "attachments",
            "status", "grade", "feedback", "submitted_at", "graded_at",
        ]
        read_only_fields = [
            "id", "exercise", "exercise_title", "status", "grade", "feedback", "submitted_at", "graded_at",
        ]


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

    class Meta:
        model = Exercise
        fields = ["id", "title", "instructions", "attachments", "deadline", "published_at", "my_submission"]
        read_only_fields = fields

    def get_my_submission(self, obj):
        child = self.context["child"]
        submission = obj.submissions.filter(child=child).first()
        return SubmissionSerializer(submission).data if submission else None


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
        exercises = virtual_class.exercises.filter(status=ExerciseStatus.PUBLISHED)
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
