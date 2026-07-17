import datetime
import secrets

from django.contrib import admin
from django.utils import timezone

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user

from .models import Certification, ExamAttempt, ExamQuestion, SessionEnrollment, TrainingModule, TrainingSession

CERTIFICATION_VALIDITY_DAYS = 730


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


@admin.register(SessionEnrollment)
class SessionEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "session", "payment_status", "attendance_score", "enrolled_at")
    list_filter = ("payment_status",)
    search_fields = ("teacher__email",)


@admin.register(ExamQuestion)
class ExamQuestionAdmin(admin.ModelAdmin):
    list_display = ("module", "question_type", "difficulty", "points", "is_active")
    list_filter = ("module", "question_type", "difficulty", "is_active")


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("teacher", "session", "status", "score_total", "started_at")
    list_filter = ("status", "is_retake")
    actions = ["approve_and_issue_certification", "reject_attempt"]

    def get_queryset(self, request):
        # Les tentatives en ligne sont notées et certifiées automatiquement
        # par l'API — cet écran d'administration ne traite que le présentiel.
        return super().get_queryset(request).filter(is_online=False)

    @admin.action(description="Approuver et délivrer la certification (change le niveau)")
    def approve_and_issue_certification(self, request, queryset):
        issued = 0
        skipped = 0
        for attempt in queryset.select_related("session__module", "teacher"):
            if hasattr(attempt, "certification"):
                skipped += 1
                continue
            if attempt.score_total is None:
                skipped += 1
                continue
            module = attempt.get_module()
            Certification.objects.create(
                teacher=attempt.teacher,
                module=module,
                attempt=attempt,
                level=module.target_level,
                score_total=attempt.score_total,
                qr_code=f"XPO-CERT-{attempt.teacher_id}-{secrets.token_hex(6).upper()}",
                expires_at=timezone.localdate() + datetime.timedelta(days=CERTIFICATION_VALIDITY_DAYS),
            )
            attempt.status = "passed"
            attempt.graded_by = request.user
            attempt.graded_at = timezone.now()
            attempt.save(update_fields=["status", "graded_by", "graded_at"])
            notify_user(
                attempt.teacher,
                NotificationType.EXAM_RESULT,
                title="Certification délivrée",
                body=f"Félicitations, votre niveau {module.target_level} pour « {module.title} » a été validé par Xporadia.",
            )
            issued += 1
        self.message_user(
            request, f"{issued} certification(s) délivrée(s), {skipped} ignorée(s) (déjà certifiées ou score manquant)."
        )

    @admin.action(description="Rejeter (échec — pas de certification délivrée)")
    def reject_attempt(self, request, queryset):
        attempts = list(
            queryset.select_related("session__module", "teacher").exclude(status="passed")
        )
        for attempt in attempts:
            attempt.status = "failed"
            attempt.save(update_fields=["status"])
            module = attempt.get_module()
            notify_user(
                attempt.teacher,
                NotificationType.EXAM_RESULT,
                title="Résultat d'examen",
                body=f"Votre tentative pour « {module.title if module else '?'} » n'a pas été validée cette fois-ci.",
            )
        self.message_user(request, f"{len(attempts)} tentative(s) marquée(s) échouée(s) et notifiée(s).")


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ("teacher", "module", "level", "score_total", "is_valid", "expires_at")
    list_filter = ("level", "is_valid")
    search_fields = ("teacher__email", "qr_code")
