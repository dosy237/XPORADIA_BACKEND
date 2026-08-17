"""
Xporadia — apps/feed/consumers.py

Même architecture que la messagerie : le WebSocket ne sert qu'à la
diffusion temps réel, toute écriture continue de passer par l'API REST
déjà testée. Deux groupes possibles :
  - "feed_global" : nouvelles publications / suppressions sur le fil
    principal — accessible sans authentification (le fil est public en
    lecture, comme l'API REST elle-même).
  - "feed_post_<id>" : commentaires et j'aime d'une publication précise,
    pour l'écran détail.
"""
import json

from channels.generic.websocket import AsyncWebsocketConsumer


class FeedConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        post_id = self.scope["url_route"]["kwargs"].get("post_id")
        self.group_name = f"feed_post_{post_id}" if post_id else "feed_global"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        await self.send(text_data=json.dumps({
            "type": "info",
            "detail": "Ce canal est en lecture seule — utilisez l'API REST pour publier ou commenter.",
        }))

    async def broadcast_event(self, event):
        await self.send(text_data=json.dumps(event["payload"]))
