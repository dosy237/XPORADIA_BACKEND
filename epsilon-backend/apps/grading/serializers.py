from rest_framework import serializers

from .models import Evaluation, EstablishmentJoinRequest, Grade, ReportCard, SubjectReportEntry, Term


class JoinRequestSerializer(serializers.ModelSerializer):
    establishment_name = serializers.SerializerMethodField()
    child_first_name = serializers.CharField(source="child.first_name", read_only=True)
    child_last_name = serializers.CharField(source="child.last_name", read_only=True)

    class Meta:
        model = EstablishmentJoinRequest
        fields = [
            "id", "child", "child_first_name", "child_last_name", "establishment",
            "establishment_name", "other_establishment_name", "declared_level",
            "status", "rejection_reason", "created_at", "reviewed_at",
        ]
        read_only_fields = [
            "id", "child", "child_first_name", "child_last_name", "establishment_name",
            "status", "rejection_reason", "created_at", "reviewed_at",
        ]

    def get_establishment_name(self, obj):
        return obj.establishment.school_name if obj.establishment else obj.other_establishment_name

    def validate(self, attrs):
        if not attrs.get("establishment") and not attrs.get("other_establishment_name"):
            raise serializers.ValidationError(
                "Précisez un établissement existant ou son nom si absent de la liste."
            )
        return attrs


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "school_year", "number", "name", "start_date", "end_date", "is_active"]
        read_only_fields = ["id"]


class EvaluationSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)

    class Meta:
        model = Evaluation
        fields = [
            "id", "subject", "subject_name", "term", "title", "eval_type",
            "coefficient", "date", "created_at",
        ]
        read_only_fields = ["id", "subject", "subject_name", "created_at"]


class GradeSerializer(serializers.ModelSerializer):
    child_first_name = serializers.CharField(source="child.first_name", read_only=True)
    child_last_name = serializers.CharField(source="child.last_name", read_only=True)

    class Meta:
        model = Grade
        fields = ["id", "evaluation", "child", "child_first_name", "child_last_name", "score", "is_excused"]
        read_only_fields = ["id", "child_first_name", "child_last_name"]


class BulkGradeEntrySerializer(serializers.Serializer):
    """Une ligne de saisie en lot — le score est optionnel (élève pas
    encore noté) mais child et is_excused sont toujours requis, pour
    permettre de traiter toute la classe en un seul envoi plutôt qu'un
    appel réseau par élève."""

    child = serializers.IntegerField()
    score = serializers.DecimalField(max_digits=4, decimal_places=2, required=False, allow_null=True)
    is_excused = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if not attrs.get("is_excused") and attrs.get("score") is None:
            return attrs  # note non encore saisie, autorisé (brouillon)
        if attrs.get("score") is not None and not (0 <= attrs["score"] <= 20):
            raise serializers.ValidationError("La note doit être comprise entre 0 et 20.")
        return attrs


class SubjectReportEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectReportEntry
        fields = ["subject_name", "subject_average", "coefficient", "teacher_comment"]
        read_only_fields = fields


class ReportCardSerializer(serializers.ModelSerializer):
    subject_entries = SubjectReportEntrySerializer(many=True, read_only=True)
    child_first_name = serializers.CharField(source="child.first_name", read_only=True)
    child_last_name = serializers.CharField(source="child.last_name", read_only=True)
    term_label = serializers.CharField(source="term.__str__", read_only=True)

    class Meta:
        model = ReportCard
        fields = [
            "id", "child", "child_first_name", "child_last_name", "term", "term_label",
            "general_average", "class_average", "rank", "class_size",
            "homeroom_comment", "document", "subject_entries", "published_at",
        ]
        read_only_fields = fields
