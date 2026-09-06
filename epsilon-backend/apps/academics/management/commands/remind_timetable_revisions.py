"""
Xporadia — remind_timetable_revisions

À exécuter une fois chaque soir (voir CELERY_BEAT_SCHEDULE dans
config/settings/base.py) : envoie, la veille de chaque jour d'école, un
rappel des cours du lendemain à chaque élève inscrit et à son parent.
Aucun rappel n'est envoyé si le lendemain est un dimanche ou tombe en
vacances (voir apps.academics.services.timetable_slots_for_date, qui
renvoie alors un queryset vide).

TimetableSlot étant récurrent par semaine (pas une instance par date),
l'idempotence ne peut pas reposer sur un champ horodaté sur le créneau
lui-même comme pour Exercise — elle est journalisée par (classe, date)
via TimetableReminderLog.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user

from ...models import Enrollment, EnrollmentStatus, SchoolClass, TimetableReminderLog
from ...services import timetable_slots_for_date


class Command(BaseCommand):
    help = "Envoie le rappel des cours du lendemain, la veille au soir."

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        classes_notified = 0

        for school_class in SchoolClass.objects.select_related("track__department__establishment"):
            slots = list(timetable_slots_for_date(school_class, tomorrow))
            if not slots:
                continue
            if TimetableReminderLog.objects.filter(school_class=school_class, date=tomorrow).exists():
                continue

            subjects = sorted({slot.subject.name for slot in slots})
            body = f"Demain : {', '.join(subjects)}."

            enrollments = Enrollment.objects.filter(
                school_class=school_class, status=EnrollmentStatus.ACTIVE
            ).select_related("child__user", "child__parent__user")

            for enrollment in enrollments:
                child = enrollment.child
                recipients = []
                if child.user_id:
                    recipients.append(child.user)
                if child.parent_id and child.parent.user_id:
                    recipients.append(child.parent.user)
                for recipient in recipients:
                    notify_user(
                        recipient,
                        NotificationType.TIMETABLE_REMINDER,
                        title="Cours de demain",
                        body=body,
                        data={"date": tomorrow.isoformat(), "school_class": str(school_class.id)},
                    )

            TimetableReminderLog.objects.create(school_class=school_class, date=tomorrow)
            classes_notified += 1

        self.stdout.write(self.style.SUCCESS(f"Rappel de cours envoyé pour {classes_notified} classe(s)."))
