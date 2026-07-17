from rest_framework import serializers

from apps.users.models import Child

from .models import (
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
            "period_start", "period_end", "places", "city", "skills_wanted",
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

    class Meta:
        model = InternshipConvention
        fields = [
            "id", "application", "pdf_url", "status",
            "signed_by_school_at", "signed_by_company_at", "generated_at",
        ]
        read_only_fields = fields


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
