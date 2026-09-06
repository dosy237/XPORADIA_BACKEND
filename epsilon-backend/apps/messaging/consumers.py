"""
Xporadia — apps/messaging/consumers.py

Architecture délibérée : le WebSocket ne sert QUE à la diffusion temps réel
(lecture) — toute écriture (envoi/édition/suppression de message) continue
de passer par l'API REST déjà testée (permissions, validation, notifications
push). Ça évite de dupliquer la logique métier à deux endroits et garde une
seule source de vérité pour les règles d'accès. Voir apps/messaging/views.py
pour les appels à broadcast_to_channel() après chaque écriture réussie.
"""
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


def _group_name(channel_id: int) -> str:
    return f"messaging_channel_{channel_id}"


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        self.group_name = _group_name(self.channel_id)
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return
        if not await self._is_member(user):
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Aucune écriture acceptée depuis le WebSocket — un client qui
        # envoie des données ici est ignoré, pas planté (message clair
        # renvoyé à titre de diagnostic pour le développement).
        await self.send(text_data=json.dumps({
            "type": "info",
            "detail": "Ce canal est en lecture seule — utilisez l'API REST pour envoyer un message.",
        }))

    async def broadcast_event(self, event):
        """Relai des événements poussés via channel_layer.group_send —
        voir apps.messaging.realtime.broadcast_to_channel."""
        await self.send(text_data=json.dumps(event["payload"]))

    @database_sync_to_async
    def _is_member(self, user) -> bool:
        from .models import ChannelMembership

        return ChannelMembership.objects.filter(channel_id=self.channel_id, user=user).exists()
