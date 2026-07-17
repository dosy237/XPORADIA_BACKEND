from django.contrib import admin

from .models import JobApplication, JobListing, JobSeekingRequest, Recruitment


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
    list_display = ["teacher", "school", "salary_agreed", "payment_status", "confirmed_at"]
    list_filter = ["payment_status"]
    search_fields = ["teacher__email", "school__email"]


@admin.register(JobSeekingRequest)
class JobSeekingRequestAdmin(admin.ModelAdmin):
    list_display = ["teacher", "city", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["teacher__email"]
