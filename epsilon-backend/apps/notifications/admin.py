from django.contrib import admin

from .models import DeviceToken, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "notif_type", "channel", "title", "is_read", "created_at"]
    list_filter = ["notif_type", "channel", "is_read"]
    search_fields = ["user__email", "title"]


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "token", "created_at", "last_used_at"]
    list_filter = ["platform"]
    search_fields = ["user__email", "token"]
