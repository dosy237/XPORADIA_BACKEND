from django.contrib import admin

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user

from .models import (
    Child,
    ChildClaimRequest,
    CompanyProfile,
    DirectorProfile,
    OTPCode,
    ParentProfile,
    PreRegistrationCode,
    StudentActivationInvite,
    TeacherComment,
    TeacherDiploma,
    TeacherProfile,
    User,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        "email", "first_name", "last_name", "primary_role",
        "is_verified", "is_documents_validated", "created_at",
    ]
    list_filter = ["primary_role", "is_verified", "is_documents_validated", "is_active"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    actions = ["validate_selected_accounts"]

    @admin.action(description="Valider le(s) compte(s) sélectionné(s) (accréditation Xporadia)")
    def validate_selected_accounts(self, request, queryset):
        updated = 0
        for user in queryset.filter(is_documents_validated=False):
            user.is_documents_validated = True
            user.save(update_fields=["is_documents_validated"])
            notify_user(
                user,
                NotificationType.SYSTEM,
                title="Votre compte Xporadia est validé",
                body=(
                    "Xporadia a validé votre formation présentielle et votre profil. "
                    "Vous êtes désormais officiellement accrédité sur la plateforme."
                ),
            )
            updated += 1
        self.message_user(request, f"{updated} compte(s) validé(s) et notifié(s).")


class TeacherDiplomaInline(admin.TabularInline):
    model = TeacherDiploma
    extra = 0


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user", "experience_years", "available_for_tutoring",
        "available_for_employment", "preregistration_code",
    ]
    inlines = [TeacherDiplomaInline]


@admin.register(PreRegistrationCode)
class PreRegistrationCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "label", "is_used", "used_by", "created_by", "created_at"]
    list_filter = ["is_used"]
    search_fields = ["code", "label", "used_by__email"]
    readonly_fields = ["used_by", "used_at", "is_used"]

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(DirectorProfile)
class DirectorProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "school_name", "is_partner"]


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "company_name", "sector", "is_partner"]


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


@admin.register(TeacherComment)
class TeacherCommentAdmin(admin.ModelAdmin):
    list_display = ["teacher", "author", "is_anonymous", "is_hidden", "created_at"]
    list_filter = ["is_anonymous", "is_hidden"]
    search_fields = ["teacher__email", "author__email", "body"]
    actions = ["hide_selected_comments", "unhide_selected_comments"]

    @admin.action(description="Masquer le(s) commentaire(s) sélectionné(s)")
    def hide_selected_comments(self, request, queryset):
        updated = queryset.update(is_hidden=True)
        self.message_user(request, f"{updated} commentaire(s) masqué(s).")

    @admin.action(description="Réafficher le(s) commentaire(s) sélectionné(s)")
    def unhide_selected_comments(self, request, queryset):
        updated = queryset.update(is_hidden=False)
        self.message_user(request, f"{updated} commentaire(s) réaffiché(s).")


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    """Enregistrement autonome, en plus de l'inline sous ParentProfile —
    sans ça, un enfant auto-inscrit sans parent (Child.parent nul, voir
    apps.grading) serait invisible nulle part dans l'administration."""

    list_display = ["first_name", "last_name", "class_level", "parent", "user"]
    list_filter = ["class_level"]
    search_fields = ["first_name", "last_name", "user__email", "parent__user__email"]


@admin.register(ChildClaimRequest)
class ChildClaimRequestAdmin(admin.ModelAdmin):
    """Surveillance des demandes de rattachement parent-enfant — utile
    pour repérer un volume anormal de demandes rejetées depuis un même
    compte parent."""

    list_display = ["parent", "child", "status", "created_at", "reviewed_at"]
    list_filter = ["status"]
    search_fields = ["parent__user__email", "child__first_name", "child__last_name"]


@admin.register(StudentActivationInvite)
class StudentActivationInviteAdmin(admin.ModelAdmin):
    list_display = ["email", "child", "is_accepted", "created_at"]
    list_filter = ["is_accepted"]
    search_fields = ["email", "child__first_name"]
