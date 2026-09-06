from rest_framework import serializers

from apps.users.models import User

from .models import (
    EmployerReview,
    EstablishmentInvoice,
    JobApplication,
    JobListing,
    JobSeekingRequest,
    PayrollEntry,
    Recruitment,
    WalletTransaction,
    WorkedHours,
)


class SchoolBasicSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="director_profile.id")
    school_name = serializers.CharField(source="director_profile.school_name")
    address = serializers.CharField(source="director_profile.address")


class TeacherBasicSerializer(serializers.ModelSerializer):
    """Identité minimale d'un enseignant vue par un directeur — jamais
    l'email ni le téléphone (le contact passe uniquement par la
    messagerie ouverte à la candidature, voir ListingApplicationsView),
    cohérent avec la règle appliquée partout ailleurs dans l'app."""

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "avatar"]
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
    can_review = serializers.SerializerMethodField()
    has_review = serializers.SerializerMethodField()

    class Meta:
        model = Recruitment
        fields = [
            "id", "teacher", "contract_type", "salary_agreed",
            "hourly_rate_teacher", "hourly_rate_billed", "requires_declared_hours",
            "commission_rate", "commission_amount", "payment_status", "confirmed_at",
            "can_review", "has_review",
        ]
        read_only_fields = fields

    def get_has_review(self, obj):
        return EmployerReview.objects.filter(recruitment=obj).exists()

    def get_can_review(self, obj):
        from django.utils import timezone

        from .constants import REVIEW_MIN_DAYS_AFTER_RECRUITMENT

        if self.get_has_review(obj):
            return False
        days_since = (timezone.now() - obj.confirmed_at).days
        return days_since >= REVIEW_MIN_DAYS_AFTER_RECRUITMENT


class CreateEmployerReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployerReview
        fields = ["atmosphere", "contract_respect", "working_conditions", "payment_timeliness", "comment"]

    def validate(self, attrs):
        for field in ["atmosphere", "contract_respect", "working_conditions", "payment_timeliness"]:
            if not (1 <= attrs[field] <= 5):
                raise serializers.ValidationError({field: "La note doit être comprise entre 1 et 5."})
        return attrs


class EstablishmentEmploymentHistorySerializer(serializers.Serializer):
    """Historique d'emploi affiché sur le profil PUBLIC d'un enseignant —
    volontairement minimal : jamais de salaire ni de tarif horaire, qui
    restent strictement privés (voir RecruitmentSerializer, réservé au
    propriétaire)."""

    id = serializers.CharField()
    school_name = serializers.CharField(source="school.director_profile.school_name")
    contract_type = serializers.CharField()
    confirmed_at = serializers.DateTimeField()


class WorkedHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkedHours
        fields = [
            "id", "recruitment", "date", "hours", "note", "status",
            "declared_at", "reviewed_at", "rejection_reason",
        ]
        read_only_fields = ["id", "recruitment", "status", "declared_at", "reviewed_at", "rejection_reason"]

    def validate_hours(self, value):
        if value <= 0 or value > 16:
            raise serializers.ValidationError("Le nombre d'heures doit être compris entre 0 et 16 par jour.")
        return value


class ReviewWorkedHoursSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    rejection_reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class PayrollEntrySerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source="recruitment.school.director_profile.school_name", read_only=True)

    class Meta:
        model = PayrollEntry
        fields = [
            "id", "recruitment", "school_name", "period_year", "period_month",
            "total_hours", "hourly_rate_teacher", "gross_amount", "created_at",
        ]
        read_only_fields = fields


class WalletTransactionSerializer(serializers.ModelSerializer):
    payroll_entry = PayrollEntrySerializer(read_only=True)

    class Meta:
        model = WalletTransaction
        fields = ["id", "payroll_entry", "amount", "created_at"]
        read_only_fields = fields


class JobSeekingRequestSerializer(serializers.ModelSerializer):
    teacher = TeacherBasicSerializer(read_only=True)

    class Meta:
        model = JobSeekingRequest
        fields = ["id", "teacher", "subjects", "city", "message", "is_active", "created_at"]
        read_only_fields = ["id", "teacher", "created_at"]


class EstablishmentInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstablishmentInvoice
        fields = [
            "id", "period_year", "period_month", "total_amount", "status",
            "created_at", "paid_at",
        ]
        read_only_fields = fields
