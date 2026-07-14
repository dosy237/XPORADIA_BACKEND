from django.contrib import admin

from .models import Certification, ExamAttempt, ExamQuestion, TrainingModule, TrainingSession


@admin.register(TrainingModule)
class TrainingModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "target_level", "price", "duration_hours", "is_active")
    list_filter = ("category", "target_level", "is_active")
    search_fields = ("title",)


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ("module", "trainer", "city", "date", "status", "enrolled_count", "capacity")
    list_filter = ("status", "city")
    date_hierarchy = "date"


@admin.register(ExamQuestion)
class ExamQuestionAdmin(admin.ModelAdmin):
    list_display = ("module", "question_type", "difficulty", "points", "is_active")
    list_filter = ("module", "question_type", "difficulty", "is_active")


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("teacher", "session", "status", "score_total", "started_at")
    list_filter = ("status", "is_retake")


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ("teacher", "module", "level", "score_total", "is_valid", "expires_at")
    list_filter = ("level", "is_valid")
    search_fields = ("teacher__email", "qr_code")
