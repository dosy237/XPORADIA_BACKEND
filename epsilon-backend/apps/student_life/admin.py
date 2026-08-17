from django.contrib import admin

from .models import BucketListItem, LifeGoal, PersonalDocument, PersonalNote


@admin.register(PersonalNote)
class PersonalNoteAdmin(admin.ModelAdmin):
    list_display = ["id", "child", "title", "subject", "updated_at"]
    search_fields = ["title", "child__first_name"]


@admin.register(PersonalDocument)
class PersonalDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "child", "name", "uploaded_at"]


@admin.register(LifeGoal)
class LifeGoalAdmin(admin.ModelAdmin):
    list_display = ["id", "child", "updated_at"]


@admin.register(BucketListItem)
class BucketListItemAdmin(admin.ModelAdmin):
    list_display = ["id", "child", "title", "is_done", "due_date"]
    list_filter = ["is_done"]
