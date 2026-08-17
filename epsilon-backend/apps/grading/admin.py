from django.contrib import admin

from .models import (
    EstablishmentJoinRequest,
    Evaluation,
    Grade,
    ReportCard,
    SubjectReportEntry,
    Term,
)


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["establishment", "school_year", "number", "is_active", "start_date", "end_date"]
    list_filter = ["school_year", "is_active"]
    search_fields = ["establishment__school_name"]


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ["title", "subject", "term", "eval_type", "coefficient", "date"]
    list_filter = ["eval_type", "term"]
    search_fields = ["title", "subject__name"]


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ["child", "evaluation", "score", "is_excused", "graded_at"]
    list_filter = ["is_excused"]
    search_fields = ["child__first_name", "child__last_name"]


class SubjectReportEntryInline(admin.TabularInline):
    model = SubjectReportEntry
    extra = 0


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ["child", "term", "school_class", "general_average", "rank", "class_size", "published_at"]
    list_filter = ["term"]
    search_fields = ["child__first_name", "child__last_name"]
    inlines = [SubjectReportEntryInline]


@admin.register(EstablishmentJoinRequest)
class EstablishmentJoinRequestAdmin(admin.ModelAdmin):
    """File des demandes de rattachement — utile pour repérer les cas
    "Autre" restés en attente longtemps (établissement pas encore sur
    Xporadia) ou tout comportement suspect (beaucoup de demandes rejetées
    d'un même compte)."""

    list_display = ["child", "establishment", "other_establishment_name", "status", "created_at", "reviewed_at"]
    list_filter = ["status"]
    search_fields = ["child__first_name", "child__last_name", "other_establishment_name"]
