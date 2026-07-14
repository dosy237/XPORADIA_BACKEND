from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.academics.models import Subject

from .models import VirtualClass


@receiver(post_save, sender=Subject)
def create_virtual_class_for_subject(sender, instance, created, **kwargs):
    if created:
        VirtualClass.objects.get_or_create(subject=instance)
