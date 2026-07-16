from django.contrib import admin

from .models import (
    InternshipApplication,
    InternshipConvention,
    InternshipEvaluation,
    InternshipJournal,
    InternshipOffer,
)


class InternshipApplicationInline(admin.TabularInline):
    model = InternshipApplication
    extra = 0


@admin.register(InternshipOffer)
class InternshipOfferAdmin(admin.ModelAdmin):
    list_display = ["title", "company", "domain", "city", "level", "is_active", "created_at"]
    list_filter = ["level", "is_active", "is_premium"]
    search_fields = ["title", "domain", "city", "company__email"]
    inlines = [InternshipApplicationInline]


@admin.register(InternshipApplication)
class InternshipApplicationAdmin(admin.ModelAdmin):
    list_display = ["student", "offer", "school", "status", "applied_at"]
    list_filter = ["status"]
    search_fields = ["student__first_name", "offer__title", "school__email"]


@admin.register(InternshipConvention)
class InternshipConventionAdmin(admin.ModelAdmin):
    list_display = ["application", "status", "signed_by_school_at", "signed_by_company_at"]
    list_filter = ["status"]


@admin.register(InternshipJournal)
class InternshipJournalAdmin(admin.ModelAdmin):
    list_display = ["convention", "date"]


@admin.register(InternshipEvaluation)
class InternshipEvaluationAdmin(admin.ModelAdmin):
    list_display = ["convention", "evaluator_type", "global_rating", "created_at"]
