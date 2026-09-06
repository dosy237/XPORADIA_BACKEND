"""
Xporadia — apps/academics/tasks.py

Enveloppes Celery des commandes de rappel d'agenda (voir CELERY_BEAT_SCHEDULE
dans config/settings/base.py), même principe que
apps.virtual_classes.tasks.remind_exercise_deadlines.
"""
from celery import shared_task
from django.core.management import call_command


@shared_task(ignore_result=True)
def remind_timetable_revisions():
    call_command("remind_timetable_revisions")


@shared_task(ignore_result=True)
def remind_personal_revisions():
    call_command("remind_personal_revisions")
