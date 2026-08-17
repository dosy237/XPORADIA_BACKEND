from rest_framework import serializers

from apps.users.models import Child

from .models import (
    CompanyReview,
    InternshipApplication,
    InternshipConvention,
    InternshipEvaluation,
    InternshipJournal,
    InternshipOffer,
)


class CompanyBasicSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="company_profile.id")
    company_name = serializers.CharField(source="company_profile.company_name")
    address = serializers.CharField(source="company_profile.address")


class SchoolBasicSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="director_profile.id")
    school_name = serializers.CharField(source="director_profile.school_name")


class ChildBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Child
        fields = ["id", "first_name", "class_level"]
        read_only_fields = fields


class InternshipOfferSerializer(serializers.ModelSerializer):
    company = CompanyBasicSerializer(read_only=True)
    application_count = serializers.SerializerMethodField()

    class Meta:
        model = InternshipOffer
        fields = [
            "id", "company", "title", "domain", "missions", "level", "duration_weeks",
            "period_start", "period_end", "places", "city", "skills_wanted", "cover_image",
            "is_premium", "is_active", "application_count", "created_at",
        ]
        read_only_fields = ["id", "company", "is_premium", "application_count", "created_at"]

    def get_application_count(self, obj):
        return obj.applications.count()


class InternshipApplicationSerializer(serializers.ModelSerializer):
    school = SchoolBasicSerializer(read_only=True)
    student = ChildBasicSerializer(read_only=True)
    offer = InternshipOfferSerializer(read_only=True)
    student_id = serializers.PrimaryKeyRelatedField(
        source="student", queryset=Child.objects.all(), write_only=True
    )

    class Meta:
        model = InternshipApplication
        fields = [
            "id", "offer", "school", "student", "student_id", "motivation",
            "status", "applied_at", "reviewed_at",
        ]
        read_only_fields = ["id", "offer", "school", "student", "status", "applied_at", "reviewed_at"]


class InternshipConventionSerializer(serializers.ModelSerializer):
    application = InternshipApplicationSerializer(read_only=True)
    channel_id = serializers.SerializerMethodField()
    has_company_review = serializers.SerializerMethodField()
    can_review_company = serializers.SerializerMethodField()

    class Meta:
        model = InternshipConvention
        fields = [
            "id", "application", "position_title", "document", "pdf_url", "status", "channel_id",
            "signed_by_school_at", "signed_by_company_at", "generated_at",
            "has_company_review", "can_review_company",
        ]
        read_only_fields = ["id", "application", "document", "pdf_url", "status", "channel_id",
                             "signed_by_school_at", "signed_by_company_at", "generated_at",
                             "has_company_review", "can_review_company"]

    def get_channel_id(self, obj):
        return getattr(getattr(obj, "channel", None), "id", None)

    def get_has_company_review(self, obj):
        return hasattr(obj, "company_review")

    def get_can_review_company(self, obj):
        from django.utils import timezone

        if self.get_has_company_review(obj):
            return False
        return obj.application.offer.period_end <= timezone.localdate()


class InternshipJournalSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternshipJournal
        fields = ["id", "date", "content", "photos", "created_at"]
        read_only_fields = ["id", "created_at"]


class InternshipEvaluationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternshipEvaluation
        fields = [
            "id", "evaluator_type", "punctuality", "initiative", "integration",
            "skills", "global_rating", "comment", "attestation_url", "created_at",
        ]
        read_only_fields = ["id", "evaluator_type", "created_at"]


class CompanyReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyReview
        fields = ["id", "atmosphere", "mentorship", "role_accuracy", "learning_value", "comment", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        for field in ["atmosphere", "mentorship", "role_accuracy", "learning_value"]:
            if not (1 <= attrs[field] <= 5):
                raise serializers.ValidationError({field: "La note doit être comprise entre 1 et 5."})
        return attrs
