"""
Xporadia — apps/messaging/realtime.py

Point d'appel unique depuis les vues REST pour pousser un événement en
temps réel aux clients WebSocket connectés à un canal. Volontairement
tolérant aux pannes : si Redis/Channels est indisponible, la requête REST
qui a écrit la donnée (déjà en base, déjà correcte) ne doit jamais échouer
à cause d'un souci de diffusion temps réel — au pire, les clients
recevront la mise à jour au prochain repli sur polling côté app.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def broadcast_to_channel(channel_id: int, event_type: str, payload: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            f"messaging_channel_{channel_id}",
            {"type": "broadcast_event", "payload": {"event": event_type, **payload}},
        )
    except Exception:
        logger.exception("Échec de diffusion temps réel sur le canal %s (event=%s)", channel_id, event_type)
