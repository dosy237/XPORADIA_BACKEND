from django.contrib import admin

from .models import LibraryResource, ResourceDownload, ResourceFavorite


@admin.register(LibraryResource)
class LibraryResourceAdmin(admin.ModelAdmin):
    list_display = ["title", "establishment", "subject", "level", "resource_type", "author", "is_archived"]
    list_filter = ["establishment", "level", "resource_type", "is_archived", "moderation_status"]
    search_fields = ["title", "subject", "establishment__school_name", "author__email"]


@admin.register(ResourceDownload)
class ResourceDownloadAdmin(admin.ModelAdmin):
    list_display = ["resource", "user", "downloaded_at"]


@admin.register(ResourceFavorite)
class ResourceFavoriteAdmin(admin.ModelAdmin):
    list_display = ["resource", "user", "added_at"]
