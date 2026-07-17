from rest_framework import serializers

from apps.payments.serializers import PaymentSerializer
from apps.users.models import User, UserRole

from .models import TutoringReview, TutoringSession


class TutoringUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name"]
        read_only_fields = fields


class TutoringSessionSerializer(serializers.ModelSerializer):
    teacher = TutoringUserSerializer(read_only=True)
    parent = TutoringUserSerializer(read_only=True)
    teacher_id = serializers.PrimaryKeyRelatedField(
        source="teacher", queryset=User.objects.filter(primary_role=UserRole.TEACHER), write_only=True
    )
    payment = serializers.SerializerMethodField()

    class Meta:
        model = TutoringSession
        fields = [
            "id", "teacher", "teacher_id", "parent", "child_name", "child_level", "subject", "mode",
            "date", "start_time", "duration_min", "address", "note_for_teacher",
            "gross_amount", "net_amount", "status", "cancel_reason", "payment", "created_at",
        ]
        read_only_fields = [
            "id", "teacher", "parent", "gross_amount", "net_amount", "status", "cancel_reason",
            "payment", "created_at",
        ]

    def get_payment(self, obj):
        payment = obj.payments.order_by("-created_at").first()
        return PaymentSerializer(payment).data if payment else None


class TutoringSessionStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutoringSession
        fields = ["status", "cancel_reason"]

    def validate_status(self, value):
        if value not in ("completed", "cancelled"):
            raise serializers.ValidationError("Seules les transitions vers 'completed' ou 'cancelled' sont permises.")
        return value


class TutoringReviewSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)

    class Meta:
        model = TutoringReview
        fields = [
            "id", "session", "author_name", "author_type", "rating", "comment",
            "teacher_reply", "created_at",
        ]
        read_only_fields = ["id", "session", "author_name", "author_type", "teacher_reply", "created_at"]

    def validate_rating(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError("La note doit être comprise entre 1 et 5.")
        return value
