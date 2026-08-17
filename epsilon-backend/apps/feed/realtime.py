"""Xporadia — apps/feed/realtime.py — voir apps.messaging.realtime pour le
principe général (tolérance aux pannes, appel synchrone)."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _send(group_name: str, event_type: str, payload: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group_name, {"type": "broadcast_event", "payload": {"event": event_type, **payload}}
        )
    except Exception:
        logger.exception("Échec de diffusion temps réel (groupe=%s, event=%s)", group_name, event_type)


def broadcast_to_feed(event_type: str, payload: dict) -> None:
    _send("feed_global", event_type, payload)


def broadcast_to_post(post_id: int, event_type: str, payload: dict) -> None:
    _send(f"feed_post_{post_id}", event_type, payload)
