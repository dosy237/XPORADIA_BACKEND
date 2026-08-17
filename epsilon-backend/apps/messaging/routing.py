from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/messaging/channel/(?P<channel_id>\d+)/$", consumers.ChatConsumer.as_asgi()),
]
