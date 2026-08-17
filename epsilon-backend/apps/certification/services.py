"""
Xporadia — apps/certification/services.py

Le total de points d'un enseignant était recalculé indépendamment à trois
endroits (StatusSerializer, deux fonctions dans apps/users/serializers.py) —
centralisé ici pour n'avoir qu'une seule définition de "combien de points
un enseignant a-t-il", réutilisable aussi bien pour l'affichage d'un profil
que pour classer l'annuaire par réputation.
"""
from django.db.models import IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce


def teacher_total_points(user) -> int:
    """Somme des points des certifications valides d'un enseignant donné."""
    from apps.certification.models import Certification

    return sum(
        Certification.objects.filter(teacher=user, is_valid=True).values_list("points_awarded", flat=True)
    )


def annotate_total_points(queryset, user_field: str = "user_id"):
    """Annote un queryset (dont chaque ligne référence un enseignant via
    `user_field`) avec `_total_points`, calculé en une seule requête plutôt
    qu'un aller-retour par ligne — utilisé pour trier l'annuaire enseignant
    par réputation (plus de points = plus de visibilité)."""
    from apps.certification.models import Certification

    points_subquery = (
        Certification.objects.filter(teacher_id=OuterRef(user_field), is_valid=True)
        .order_by()
        .values("teacher_id")
        .annotate(total=Sum("points_awarded"))
        .values("total")
    )
    return queryset.annotate(
        _total_points=Coalesce(Subquery(points_subquery, output_field=IntegerField()), 0)
    )
