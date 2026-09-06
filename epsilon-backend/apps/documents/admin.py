from django.contrib import admin

from .models import AdministrativeDocument


@admin.register(AdministrativeDocument)
class AdministrativeDocumentAdmin(admin.ModelAdmin):
    list_display = ["reference_number", "child", "document_type", "school_year", "issued_at"]
    list_filter = ["document_type", "school_year"]
    search_fields = ["reference_number", "child__first_name", "child__last_name"]
