from django.contrib import admin

from .models import DisciplinaryIncident


@admin.register(DisciplinaryIncident)
class DisciplinaryIncidentAdmin(admin.ModelAdmin):
    list_display = ["child", "school_class", "occurred_on", "severity", "sanction"]
    list_filter = ["severity", "sanction"]
    search_fields = ["child__first_name", "child__last_name"]
