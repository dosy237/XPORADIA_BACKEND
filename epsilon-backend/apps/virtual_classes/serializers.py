from rest_framework import serializers

from .models import Exercise, VirtualClass


class ExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercise
        fields = [
            "id", "title", "instructions", "attachments", "deadline",
            "status", "published_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "published_at", "created_at", "updated_at"]


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
