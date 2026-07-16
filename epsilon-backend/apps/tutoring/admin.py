from django.contrib import admin

from .models import TutoringReview, TutoringSession, TutoringSubscription


@admin.register(TutoringSession)
class TutoringSessionAdmin(admin.ModelAdmin):
    list_display = ["teacher", "parent", "subject", "date", "status", "gross_amount", "net_amount"]
    list_filter = ["status", "mode"]
    search_fields = ["teacher__email", "parent__email", "child_name"]


@admin.register(TutoringReview)
class TutoringReviewAdmin(admin.ModelAdmin):
    list_display = ["session", "author", "rating", "is_moderated", "created_at"]
    list_filter = ["is_moderated", "rating"]


@admin.register(TutoringSubscription)
class TutoringSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["parent", "teacher", "subject", "monthly_rate", "is_active", "start_date"]
    list_filter = ["is_active"]
