"""
Envoi de notifications — crée toujours la trace in-app, et tente en plus un
envoi push (Expo Push Service) si l'utilisateur a des appareils enregistrés.

Le push est best-effort : une erreur réseau vers Expo ne doit jamais faire
échouer l'action métier (validation de compte, délivrance de certificat...)
qui déclenche la notification.

Envoi synchrone pour l'instant — Celery est déjà dans requirements/base.txt
et configuré dans settings (broker Redis) pour de futurs traitements
asynchrones, mais aucun worker ne tourne dans cet environnement de dev.
Cette fonction est écrite pour pouvoir être triviallement enveloppée dans une
tâche Celery (`@shared_task`) le jour où le volume l'impose.
"""
import logging

import requests

from .constants import CATEGORY_BY_NOTIF_TYPE
from .models import Notification, NotificationPreference

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_PUSH_TIMEOUT_SECONDS = 5


def notify_user(user, notif_type, title, body, data=None, send_push=True):
    """Crée la notification in-app et tente l'envoi push. Ne fait rien
    (renvoie None) si l'utilisateur a désactivé la catégorie de ce
    notif_type — seul point de tout le projet qui consulte cette
    préférence, aucune autre logique d'envoi à dupliquer. Retourne la
    Notification créée sinon."""
    category = CATEGORY_BY_NOTIF_TYPE.get(notif_type)
    if category and NotificationPreference.objects.filter(
        user=user, category=category, enabled=False
    ).exists():
        return None
    notification = Notification.objects.create(
        user=user,
        notif_type=notif_type,
        channel="inapp",
        title=title,
        body=body,
        data=data or {},
    )
    if send_push:
        _send_expo_push(user, title, body, data or {})
    return notification


def _send_expo_push(user, title, body, data):
    tokens = list(user.device_tokens.values_list("token", flat=True))
    if not tokens:
        return
    messages = [
        {"to": token, "title": title, "body": body, "data": data, "sound": "default"}
        for token in tokens
    ]
    try:
        response = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=EXPO_PUSH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("Échec de l'envoi push Expo pour %s", user.email, exc_info=True)
