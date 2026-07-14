from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "notif_type", "channel", "title", "is_read", "created_at"]
    list_filter = ["notif_type", "channel", "is_read"]
    search_fields = ["user__email", "title"]
