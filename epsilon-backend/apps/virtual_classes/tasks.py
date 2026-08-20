"""
Xporadia — apps/virtual_classes/tasks.py

Enveloppe Celery de la commande `remind_exercise_deadlines` (voir ce
fichier pour la logique) — nécessaire pour qu'un beat Celery puisse la
déclencher périodiquement (voir CELERY_BEAT_SCHEDULE dans
config/settings/base.py). La commande existait déjà mais n'était appelée
par rien : sans cette tâche, aucun rappel n'était jamais envoyé.
"""
from celery import shared_task
from django.core.management import call_command


@shared_task(ignore_result=True)
def remind_exercise_deadlines():
    call_command("remind_exercise_deadlines")
