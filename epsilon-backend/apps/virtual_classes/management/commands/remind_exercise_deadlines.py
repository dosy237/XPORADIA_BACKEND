"""
Xporadia — remind_exercise_deadlines

À exécuter périodiquement (toutes les 15-30 min via Celery Beat en
production ; cron ou déclenchement manuel en attendant). Deux rappels :

  1. "Bientôt à rendre" — devoir publié, échéance dans moins de 24h,
     envoyé aux élèves/parents qui n'ont pas encore soumis.
  2. "Échéance dépassée" — devoir publié, échéance passée, même ciblage
     (ceux qui n'ont toujours pas rendu).

Chaque rappel n'est envoyé qu'une fois par devoir (voir
due_soon_notified_at / overdue_notified_at sur Exercise).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.academics.models import Enrollment, EnrollmentStatus
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.virtual_classes.models import Exercise, ExerciseStatus, Submission


def _students_without_submission(exercise):
    school_class = exercise.virtual_class.subject.school_class
    submitted_child_ids = set(
        Submission.objects.filter(exercise=exercise).values_list("child_id", flat=True)
    )
    enrollments = Enrollment.objects.filter(
        school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).exclude(child_id__in=submitted_child_ids).select_related("child__user", "child__parent__user")

    recipients = []
    for enrollment in enrollments:
        child = enrollment.child
        # L'élève est notifié dès qu'il a activé son propre compte ; le
        # parent, s'il existe, est notifié EN PLUS — jamais à la place.
        # Le parent seul n'est légitime que si l'enfant n'a pas encore de
        # compte propre.
        if child.user_id:
            recipients.append(child.user)
        if child.parent_id and child.parent.user_id:
            recipients.append(child.parent.user)
    return recipients


class Command(BaseCommand):
    help = "Envoie les rappels d'échéance de devoirs (bientôt dû / en retard)."

    def handle(self, *args, **options):
        now = timezone.now()
        due_soon_count = 0
        overdue_count = 0

        due_soon_qs = Exercise.objects.filter(
            status=ExerciseStatus.PUBLISHED,
            deadline__isnull=False,
            deadline__gt=now,
            deadline__lte=now + timedelta(hours=24),
            due_soon_notified_at__isnull=True,
        ).select_related("virtual_class__subject__school_class")

        for exercise in due_soon_qs:
            for recipient in _students_without_submission(exercise):
                notify_user(
                    recipient,
                    NotificationType.EXERCISE_DUE_SOON,
                    title="Devoir à rendre bientôt",
                    body=f"« {exercise.title} » est à rendre avant demain.",
                    data={"exercise_id": str(exercise.id)},
                )
            exercise.due_soon_notified_at = now
            exercise.save(update_fields=["due_soon_notified_at"])
            due_soon_count += 1

        overdue_qs = Exercise.objects.filter(
            status=ExerciseStatus.PUBLISHED,
            deadline__isnull=False,
            deadline__lte=now,
            overdue_notified_at__isnull=True,
        ).select_related("virtual_class__subject__school_class")

        for exercise in overdue_qs:
            for recipient in _students_without_submission(exercise):
                notify_user(
                    recipient,
                    NotificationType.EXERCISE_OVERDUE,
                    title="Devoir non rendu",
                    body=f"La date limite pour « {exercise.title} » est passée, vous pouvez encore le rendre.",
                    data={"exercise_id": str(exercise.id)},
                )
            exercise.overdue_notified_at = now
            exercise.save(update_fields=["overdue_notified_at"])
            overdue_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Rappels envoyés — bientôt dus : {due_soon_count} devoir(s), "
                f"en retard : {overdue_count} devoir(s)."
            )
        )
