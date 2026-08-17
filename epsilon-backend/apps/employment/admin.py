from django.contrib import admin

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


class JobApplicationInline(admin.TabularInline):
    model = JobApplication
    extra = 0


@admin.register(JobListing)
class JobListingAdmin(admin.ModelAdmin):
    list_display = ["title", "school", "subject", "city", "status", "created_at"]
    list_filter = ["status", "contract_type", "cert_level_required"]
    search_fields = ["title", "subject", "city", "school__email"]
    inlines = [JobApplicationInline]


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ["teacher", "listing", "status", "applied_at"]
    list_filter = ["status"]
    search_fields = ["teacher__email", "listing__title"]


@admin.register(Recruitment)
class RecruitmentAdmin(admin.ModelAdmin):
    list_display = [
        "teacher", "school", "contract_type", "salary_agreed",
        "hourly_rate_teacher", "hourly_rate_billed", "payment_status", "confirmed_at",
    ]
    list_filter = ["payment_status", "contract_type"]
    search_fields = ["teacher__email", "school__email"]


@admin.register(JobSeekingRequest)
class JobSeekingRequestAdmin(admin.ModelAdmin):
    list_display = ["teacher", "city", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["teacher__email"]


@admin.register(EmployerReview)
class EmployerReviewAdmin(admin.ModelAdmin):
    """Modération des avis enseignant → établissement — is_moderated
    contrôle l'affichage public agrégé, voir EstablishmentDirectoryDetailSerializer."""

    list_display = [
        "recruitment", "atmosphere", "contract_respect", "working_conditions",
        "payment_timeliness", "is_moderated", "created_at",
    ]
    list_filter = ["is_moderated"]
    actions = ["approve_selected"]

    @admin.action(description="Approuver (rendre visible publiquement)")
    def approve_selected(self, request, queryset):
        updated = queryset.update(is_moderated=True)
        self.message_user(request, f"{updated} avis approuvé(s).")


@admin.register(WorkedHours)
class WorkedHoursAdmin(admin.ModelAdmin):
    list_display = ["recruitment", "date", "hours", "status", "declared_at", "reviewed_by"]
    list_filter = ["status"]
    search_fields = ["recruitment__teacher__email"]


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    """Le cœur financier de la paie enseignant — visibilité complète pour
    l'administrateur sur ce qui a réellement été versé et facturé."""

    list_display = [
        "recruitment", "period_month", "period_year", "total_hours",
        "gross_amount", "billed_amount", "xporadia_margin", "created_at",
    ]
    list_filter = ["period_year", "period_month"]
    search_fields = ["recruitment__teacher__email"]


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ["teacher", "amount", "payroll_entry", "created_at"]
    search_fields = ["teacher__email"]


@admin.register(EstablishmentInvoice)
class EstablishmentInvoiceAdmin(admin.ModelAdmin):
    list_display = ["establishment", "period_month", "period_year", "total_amount", "status", "paid_at"]
    list_filter = ["status", "period_year", "period_month"]
    search_fields = ["establishment__school_name"]
