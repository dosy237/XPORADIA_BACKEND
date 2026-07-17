from django.contrib import admin

from .models import Exercise, Submission, VirtualClass


class ExerciseInline(admin.TabularInline):
    model = Exercise
    extra = 0


@admin.register(VirtualClass)
class VirtualClassAdmin(admin.ModelAdmin):
    list_display = ["subject", "teacher", "is_active", "created_at"]
    search_fields = ["subject__name", "subject__teacher__email"]
    inlines = [ExerciseInline]

    @admin.display(description="Enseignant dédié")
    def teacher(self, obj):
        return obj.subject.teacher


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ["title", "virtual_class", "status", "deadline"]
    list_filter = ["status"]
    search_fields = ["title", "virtual_class__subject__name"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["child", "exercise", "status", "grade", "submitted_at"]
    list_filter = ["status"]
    search_fields = ["child__first_name", "exercise__title"]
