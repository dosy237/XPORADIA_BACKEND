"""
Xporadia — remind_personal_revisions

À exécuter fréquemment (voir CELERY_BEAT_SCHEDULE dans
config/settings/base.py, toutes les 15 minutes comme
remind_exercise_deadlines) : pour chaque créneau personnel de révision de
l'élève dont l'heure de début tombe dans les 30 prochaines minutes,
aujourd'hui, envoie « Il est bientôt l'heure de réviser [matière] ».

Distinct de remind_timetable_revisions (rappel des cours officiels du
lendemain) — ici, rappel progressif des créneaux PERSONNELS du jour même,
un par un à mesure que la soirée avance. Aucun rappel pour un créneau déjà
passé, annulé via exception, ou un jour où l'élève n'a rien planifié.

PersonalScheduleBlock étant récurrent (pas une instance par date),
l'idempotence est journalisée par (créneau, date) via
PersonalBlockReminderLog, comme pour remind_timetable_revisions.
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user

from ...models import PersonalBlockReminderLog, PersonalScheduleBlock, PersonalScheduleException


class Command(BaseCommand):
    help = "Rappel progressif des créneaux personnels de révision à venir dans les 30 prochaines minutes."

    def handle(self, *args, **options):
        now = timezone.localtime()
        today = now.date()
        weekday = today.weekday()
        window_end = now + timedelta(minutes=30)

        blocks = PersonalScheduleBlock.objects.filter(
            weekday=weekday, valid_from__lte=today,
        ).exclude(
            valid_until__lt=today
        ).select_related("child__user", "subject")

        exceptions = {
            exc.block_id: exc
            for exc in PersonalScheduleException.objects.filter(block__in=blocks, date=today).select_related("subject")
        }

        sent_count = 0
        for block in blocks:
            exception = exceptions.get(block.id)
            if exception and exception.is_cancelled:
                continue
            if not block.child.user_id:
                continue

            start_time = exception.start_time if (exception and exception.start_time) else block.start_time
            title = exception.title if (exception and exception.title) else block.title
            subject = exception.subject if (exception and exception.subject_id) else block.subject

            start_dt = timezone.make_aware(datetime.combine(today, start_time)) \
                if timezone.is_naive(datetime.combine(today, start_time)) else datetime.combine(today, start_time)
            if not (now <= start_dt <= window_end):
                continue
            if PersonalBlockReminderLog.objects.filter(block=block, date=today).exists():
                continue

            label = subject.name if subject else title
            notify_user(
                block.child.user,
                NotificationType.REVISION_REMINDER,
                title="Révision bientôt",
                body=f"Il est bientôt l'heure de réviser {label}.",
                data={"date": today.isoformat(), "block": str(block.id)},
            )
            PersonalBlockReminderLog.objects.create(block=block, date=today)
            sent_count += 1

        self.stdout.write(self.style.SUCCESS(f"Rappel de révision envoyé pour {sent_count} créneau(x)."))
