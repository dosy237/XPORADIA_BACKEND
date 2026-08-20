from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import LibraryResource, ResourceRating


def _recompute_rating(resource_id):
    aggregate = ResourceRating.objects.filter(resource_id=resource_id).aggregate(avg=Avg("score"), count=Count("id"))
    count = aggregate["count"] or 0
    avg = (
        Decimal(str(aggregate["avg"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if count
        else Decimal("0")
    )
    # .update() plutôt que .save() — évite de redéclencher inutilement les
    # signaux/auto_now de LibraryResource pour un simple recalcul dérivé.
    LibraryResource.objects.filter(pk=resource_id).update(avg_rating=avg, ratings_count=count)


@receiver(post_save, sender=ResourceRating)
def update_avg_rating_on_save(sender, instance, **kwargs):
    _recompute_rating(instance.resource_id)


@receiver(post_delete, sender=ResourceRating)
def update_avg_rating_on_delete(sender, instance, **kwargs):
    _recompute_rating(instance.resource_id)
