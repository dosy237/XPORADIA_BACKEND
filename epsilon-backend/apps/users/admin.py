from django.contrib import admin

from .models import (
    Child,
    DirectorProfile,
    OTPCode,
    ParentProfile,
    TeacherDiploma,
    TeacherProfile,
    User,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "first_name", "last_name", "primary_role", "is_verified", "created_at"]
    list_filter = ["primary_role", "is_verified", "is_active"]
    search_fields = ["email", "first_name", "last_name", "phone"]


class TeacherDiplomaInline(admin.TabularInline):
    model = TeacherDiploma
    extra = 0


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "experience_years", "available_for_tutoring", "available_for_employment"]
    inlines = [TeacherDiplomaInline]


@admin.register(DirectorProfile)
class DirectorProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "school_name", "is_partner"]


class ChildInline(admin.TabularInline):
    model = Child
    extra = 0


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "location", "subscription_active"]
    inlines = [ChildInline]


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ["user", "purpose", "created_at", "expires_at", "used"]
    list_filter = ["purpose", "used"]
