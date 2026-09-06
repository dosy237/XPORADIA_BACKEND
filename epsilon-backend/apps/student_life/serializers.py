from rest_framework import serializers

from .models import BucketListItem, LifeGoal, PersonalDocument, PersonalNote


class PersonalNoteSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True, default=None)

    class Meta:
        model = PersonalNote
        fields = ["id", "subject", "subject_name", "title", "content", "attachments", "created_at", "updated_at"]
        read_only_fields = ["id", "subject_name", "created_at", "updated_at"]


class PersonalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonalDocument
        fields = ["id", "name", "file", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]


class LifeGoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = LifeGoal
        fields = ["description", "related_subjects", "updated_at"]
        read_only_fields = ["updated_at"]


class BucketListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BucketListItem
        fields = ["id", "title", "description", "is_done", "due_date", "created_at", "done_at"]
        read_only_fields = ["id", "created_at", "done_at"]
