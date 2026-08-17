"""
Xporadia — ASGI config (HTTP + WebSocket via Django Channels)
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

django_asgi_app = get_asgi_application()

# Import différé après get_asgi_application() — les apps Django doivent être
# chargées avant qu'on importe des modules qui touchent aux modèles
# (les routings importent des consumers qui importent des modèles).
from apps.feed.routing import websocket_urlpatterns as feed_ws_patterns  # noqa: E402
from apps.messaging.routing import websocket_urlpatterns as messaging_ws_patterns  # noqa: E402
from config.jwt_ws_auth import JWTAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddleware(
        URLRouter(messaging_ws_patterns + feed_ws_patterns)
    ),
})
