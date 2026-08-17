from django.contrib import admin

from .models import (
    Department,
    Enrollment,
    SchoolClass,
    Subject,
    TaskDelegation,
    TeacherInvitation,
    TimetableSlot,
    Track,
)


class TrackInline(admin.TabularInline):
    model = Track
    extra = 0


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "establishment"]
    list_filter = ["establishment"]
    search_fields = ["name", "establishment__school_name"]
    inlines = [TrackInline]


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ["name", "department"]
    search_fields = ["name", "department__name"]


class SubjectInline(admin.TabularInline):
    model = Subject
    extra = 0


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ["name", "track", "school_year", "homeroom_teacher", "is_active"]
    list_filter = ["school_year", "is_active"]
    search_fields = ["name", "track__name", "homeroom_teacher__email"]
    inlines = [SubjectInline]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["name", "school_class", "teacher", "coefficient"]
    search_fields = ["name", "school_class__name", "teacher__email"]


@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ["school_class", "subject", "weekday", "start_time", "end_time", "room"]
    list_filter = ["weekday"]
    search_fields = ["school_class__name", "subject__name"]


@admin.register(TaskDelegation)
class TaskDelegationAdmin(admin.ModelAdmin):
    """Le mécanisme du "censeur" — enseignants délégués sur une tâche
    précise à l'échelle de l'établissement (voir apps.academics.views,
    DelegatedTask)."""

    list_display = ["establishment", "teacher", "task", "granted_at"]
    list_filter = ["task"]
    search_fields = ["establishment__school_name", "teacher__email"]


@admin.register(TeacherInvitation)
class TeacherInvitationAdmin(admin.ModelAdmin):
    list_display = ["email", "subject", "is_accepted", "invited_by", "created_at"]
    list_filter = ["is_accepted"]
    search_fields = ["email", "subject__name"]
    readonly_fields = ["token", "accepted_by", "accepted_at"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["child", "school_class", "status", "enrolled_at", "ended_at"]
    list_filter = ["status", "school_class__school_year"]
    search_fields = ["child__first_name", "school_class__name"]
