from django.contrib import admin

from .models import Channel, ChannelMembership, Message


class ChannelMembershipInline(admin.TabularInline):
    model = ChannelMembership
    extra = 0


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ["id", "channel_type", "school_class", "subject", "is_archived", "created_at"]
    list_filter = ["channel_type", "is_archived"]
    inlines = [ChannelMembershipInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "channel", "author", "body", "is_pinned", "created_at"]
    list_filter = ["is_pinned"]
    search_fields = ["body", "author__first_name", "author__last_name"]
