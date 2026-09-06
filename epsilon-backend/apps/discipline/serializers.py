from rest_framework import serializers

from .models import DisciplinaryIncident


class DisciplinaryIncidentSerializer(serializers.ModelSerializer):
    severity_label = serializers.CharField(source="get_severity_display", read_only=True)
    sanction_label = serializers.CharField(source="get_sanction_display", read_only=True)
    child_name = serializers.SerializerMethodField()
    class_name = serializers.CharField(source="school_class.__str__", read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DisciplinaryIncident
        fields = [
            "id",
            "child",
            "child_name",
            "school_class",
            "class_name",
            "occurred_on",
            "description",
            "severity",
            "severity_label",
            "sanction",
            "sanction_label",
            "recorded_by_name",
            "parent_notified_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_child_name(self, obj):
        return f"{obj.child.first_name} {obj.child.last_name}".strip()

    def get_recorded_by_name(self, obj):
        return obj.recorded_by.get_full_name() if obj.recorded_by else ""


class RecordIncidentSerializer(serializers.Serializer):
    occurred_on = serializers.DateField()
    description = serializers.CharField()
    severity = serializers.ChoiceField(choices=DisciplinaryIncident._meta.get_field("severity").choices)
    sanction = serializers.ChoiceField(
        choices=DisciplinaryIncident._meta.get_field("sanction").choices, default="none"
    )
