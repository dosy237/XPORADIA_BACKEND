from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import UserRole


def require_admin_scope(user, *scopes: str) -> None:
    """Lève une erreur si l'utilisateur n'est pas administrateur, ou si son
    périmètre (voir AdminScope) ne couvre pas la tâche demandée. Un
    administrateur FULL passe toujours, quels que soient les `scopes`."""

    if not getattr(user, "is_authenticated", False) or not user.has_role(UserRole.ADMIN):
        raise PermissionDenied("Réservé aux administrateurs.")
    if not user.admin_has_scope(*scopes):
        raise PermissionDenied("Votre compte administrateur n'a pas accès à cette section.")


class AdminScopePermission(BasePermission):
    """Équivalent de require_admin_scope sous forme de permission_classes
    DRF, pour les ViewSets qui utilisaient jusqu'ici IsAdminUser (lequel ne
    vérifie que is_staff, sans aucune notion de périmètre)."""

    required_scopes: tuple = ()

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.admin_has_scope(*self.required_scopes))


def admin_scope_permission(*scopes: str):
    return type("ScopedAdminPermission", (AdminScopePermission,), {"required_scopes": scopes})
