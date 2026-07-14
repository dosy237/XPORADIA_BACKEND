from rest_framework import serializers

from .models import Certification, CertificationLevel, TrainingModule, TrainingSession

LEVEL_ORDER = [CertificationLevel.BRONZE, CertificationLevel.SILVER, CertificationLevel.GOLD]


class TrainingModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingModule
        fields = [
            "id", "title", "category", "description", "objectives", "prerequisites",
            "duration_hours", "price", "target_level",
        ]


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


class CertificationSerializer(serializers.ModelSerializer):
    module = TrainingModuleSerializer(read_only=True)

    class Meta:
        model = Certification
        fields = [
            "id", "module", "level", "score_total", "qr_code", "pdf_url",
            "issued_at", "expires_at", "is_valid",
        ]
        read_only_fields = fields


class MyCertificationStatusSerializer(serializers.Serializer):
    current_level = serializers.ChoiceField(choices=CertificationLevel.choices, allow_null=True)
    next_level = serializers.ChoiceField(choices=CertificationLevel.choices, allow_null=True)
    levels_achieved = serializers.ListField(child=serializers.CharField())
    certifications = CertificationSerializer(many=True)

    @staticmethod
    def build(user):
        valid_certifications = list(
            Certification.objects.filter(teacher=user, is_valid=True)
            .select_related("module")
            .order_by("-issued_at")
        )
        levels_achieved = {c.level for c in valid_certifications}
        current_level = None
        for level in reversed(LEVEL_ORDER):
            if level in levels_achieved:
                current_level = level
                break
        if current_level is None:
            next_level = LEVEL_ORDER[0]
        else:
            idx = LEVEL_ORDER.index(current_level)
            next_level = LEVEL_ORDER[idx + 1] if idx + 1 < len(LEVEL_ORDER) else None
        return {
            "current_level": current_level,
            "next_level": next_level,
            "levels_achieved": [lvl for lvl in LEVEL_ORDER if lvl in levels_achieved],
            "certifications": valid_certifications,
        }
