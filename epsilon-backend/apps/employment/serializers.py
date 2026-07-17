from rest_framework import serializers

from apps.users.models import User

from .models import JobApplication, JobListing, JobSeekingRequest, Recruitment


class SchoolBasicSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="director_profile.id")
    school_name = serializers.CharField(source="director_profile.school_name")
    address = serializers.CharField(source="director_profile.address")


class TeacherBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email"]
        read_only_fields = fields


class JobListingSerializer(serializers.ModelSerializer):
    school = SchoolBasicSerializer(read_only=True)
    # Le directeur connaît l'email des enseignants "open to work" qu'il veut
    # cibler — pas leur ID interne, même logique que partout ailleurs.
    targeted_teacher_emails = serializers.ListField(
        child=serializers.EmailField(), write_only=True, required=False
    )
    application_count = serializers.SerializerMethodField()

    class Meta:
        model = JobListing
        fields = [
            "id", "school", "title", "subject", "levels", "contract_type",
            "salary_min", "salary_max", "cert_level_required", "description",
            "city", "commune", "start_date", "status", "targeted_teacher_emails",
            "application_count", "published_at", "expires_at", "created_at",
        ]
        read_only_fields = ["id", "school", "status", "application_count", "published_at", "created_at"]

    def get_application_count(self, obj):
        return obj.applications.count()


class JobApplicationSerializer(serializers.ModelSerializer):
    teacher = TeacherBasicSerializer(read_only=True)
    listing = JobListingSerializer(read_only=True)

    class Meta:
        model = JobApplication
        fields = [
            "id", "teacher", "listing", "cover_letter", "status",
            "applied_at", "viewed_at", "rejection_reason",
        ]
        read_only_fields = ["id", "teacher", "listing", "status", "applied_at", "viewed_at"]


class RecruitmentSerializer(serializers.ModelSerializer):
    teacher = TeacherBasicSerializer(read_only=True)

    class Meta:
        model = Recruitment
        fields = [
            "id", "teacher", "salary_agreed", "commission_rate",
            "commission_amount", "payment_status", "confirmed_at",
        ]
        read_only_fields = fields


class JobSeekingRequestSerializer(serializers.ModelSerializer):
    teacher = TeacherBasicSerializer(read_only=True)

    class Meta:
        model = JobSeekingRequest
        fields = ["id", "teacher", "subjects", "city", "message", "is_active", "created_at"]
        read_only_fields = ["id", "teacher", "created_at"]
