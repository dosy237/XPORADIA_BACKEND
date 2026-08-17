from rest_framework import serializers

from apps.payments.serializers import PaymentSerializer

from .models import (
    Certification,
    CertificationLevel,
    ExamAttempt,
    ExamQuestion,
    QuestionType,
    SessionEnrollment,
    TrainingModule,
    TrainingSession,
)

LEVEL_ORDER = [
    CertificationLevel.BRONZE,
    CertificationLevel.SILVER,
    CertificationLevel.GOLD,
    CertificationLevel.PLATINUM,
    CertificationLevel.DIAMOND,
]
ONLINE_GRADABLE_TYPES = [QuestionType.MCQ, QuestionType.TF]


class TrainingModuleSerializer(serializers.ModelSerializer):
    has_online_exam = serializers.SerializerMethodField()

    class Meta:
        model = TrainingModule
        fields = [
            "id", "title", "category", "description", "objectives", "prerequisites",
            "duration_hours", "price", "target_level", "cover_image", "has_online_exam",
        ]

    def get_has_online_exam(self, obj):
        return obj.questions.filter(question_type__in=ONLINE_GRADABLE_TYPES, is_active=True).exists()


class AdminTrainingModuleSerializer(serializers.ModelSerializer):
    """Vue complète pour la gestion — contrairement au catalogue public,
    expose et permet de régler is_active et points (jamais réglables par
    n'importe qui, voir DelegatedTask/permissions similaires ailleurs)."""

    class Meta:
        model = TrainingModule
        fields = [
            "id", "title", "category", "description", "objectives", "prerequisites",
            "duration_hours", "price", "points", "target_level", "cover_image", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ExamQuestionSerializer(serializers.ModelSerializer):
    """Question d'examen en ligne — n'expose jamais correct_answer, pour éviter la triche."""

    class Meta:
        model = ExamQuestion
        fields = ["id", "question_type", "text", "options", "points"]
        read_only_fields = fields


class ExamAttemptResultSerializer(serializers.ModelSerializer):
    module = TrainingModuleSerializer(read_only=True)
    leveled_up = serializers.BooleanField(read_only=True, default=False)
    new_level = serializers.CharField(read_only=True, allow_null=True, default=None)

    class Meta:
        model = ExamAttempt
        fields = ["id", "module", "score_total", "status", "submitted_at", "leveled_up", "new_level"]
        read_only_fields = fields


class TrainingSessionSerializer(serializers.ModelSerializer):
    module = TrainingModuleSerializer(read_only=True)
    places_left = serializers.IntegerField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)

    class Meta:
        model = TrainingSession
        fields = [
            "id", "module", "trainer", "city", "location", "date",
            "start_time", "end_time", "capacity", "enrolled_count", "places_left",
            "is_full", "status",
        ]
        read_only_fields = fields


class SessionEnrollmentSerializer(serializers.ModelSerializer):
    session = TrainingSessionSerializer(read_only=True)
    payment = PaymentSerializer(read_only=True)

    class Meta:
        model = SessionEnrollment
        fields = ["id", "session", "payment_status", "attendance_score", "payment", "enrolled_at"]
        read_only_fields = fields


class CertificationSerializer(serializers.ModelSerializer):
    module = TrainingModuleSerializer(read_only=True)

    class Meta:
        model = Certification
        fields = [
            "id", "module", "level", "score_total", "qr_code", "document", "pdf_url",
            "issued_at", "expires_at", "is_valid",
        ]
        read_only_fields = fields


class PublicCertificationVerificationSerializer(serializers.ModelSerializer):
    """Réponse de la page de vérification publique (/verify/<code>) — nom
    complet de l'enseignant et intitulé du module seulement, jamais
    l'email, le téléphone, ou tout autre champ personnel. Consultable sans
    compte Xporadia, cohérent avec l'usage terrain (un directeur qui scanne
    un certificat papier)."""

    teacher_name = serializers.CharField(source="teacher.get_full_name", read_only=True)
    module_title = serializers.CharField(source="module.title", read_only=True)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Certification
        fields = [
            "teacher_name", "module_title", "level", "issued_at", "expires_at", "is_valid", "is_expired",
        ]
        read_only_fields = fields

    def get_is_expired(self, obj):
        from django.utils import timezone

        return timezone.localdate() > obj.expires_at


class MyCertificationStatusSerializer(serializers.Serializer):
    current_level = serializers.ChoiceField(choices=CertificationLevel.choices, allow_null=True)
    total_points = serializers.IntegerField()
    next_level = serializers.ChoiceField(choices=CertificationLevel.choices, allow_null=True)
    points_needed_for_next = serializers.IntegerField(allow_null=True)
    levels_achieved = serializers.ListField(child=serializers.CharField())
    certifications = CertificationSerializer(many=True)

    @staticmethod
    def build(user):
        from .constants import badge_for_points, points_to_next_level
        from .services import teacher_total_points

        valid_certifications = list(
            Certification.objects.filter(teacher=user, is_valid=True)
            .select_related("module")
            .order_by("-issued_at")
        )
        levels_achieved = {c.level for c in valid_certifications}
        total_points = teacher_total_points(user)
        current_level = badge_for_points(total_points)
        next_info = points_to_next_level(total_points)
        return {
            "current_level": current_level,
            "total_points": total_points,
            "next_level": next_info["next_level"] if next_info else None,
            "points_needed_for_next": next_info["points_needed"] if next_info else None,
            "levels_achieved": [lvl for lvl in LEVEL_ORDER if lvl in levels_achieved],
            "certifications": valid_certifications,
        }
