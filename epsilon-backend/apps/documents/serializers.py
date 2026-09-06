from rest_framework import serializers

from .models import AdministrativeDocument, AdministrativeDocumentType


class AdministrativeDocumentSerializer(serializers.ModelSerializer):
    document_type_label = serializers.CharField(source="get_document_type_display", read_only=True)
    issued_by_name = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = AdministrativeDocument
        fields = [
            "id",
            "document_type",
            "document_type_label",
            "school_year",
            "reference_number",
            "issued_at",
            "issued_by_name",
            "pdf_url",
        ]
        read_only_fields = fields

    def get_issued_by_name(self, obj):
        return obj.issued_by.get_full_name() if obj.issued_by else ""

    def get_pdf_url(self, obj):
        path = f"/api/v1/documents/administrative/{obj.id}/pdf/"
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


class IssueAdministrativeDocumentSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=AdministrativeDocumentType.choices)
    school_year = serializers.CharField(max_length=9)
