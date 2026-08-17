"""
Xporadia — config/jwt_ws_auth.py

L'app utilise des JWT (simplejwt), pas des sessions Django — l'AuthMiddlewareStack
standard de Channels (basé sur les sessions) n'authentifierait donc personne.
Ce middleware lit le token dans le paramètre de requête `?token=` (l'API
WebSocket standard ne permet pas d'en-têtes custom depuis React Native,
contrairement à une requête HTTP classique) et résout l'utilisateur associé,
exactement comme le fait JWTAuthentication côté REST.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def _get_user_from_token(token: str):
    from apps.users.models import User

    try:
        validated = AccessToken(token)
        return User.objects.get(pk=validated["user_id"])
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]
        scope["user"] = await _get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
