 
# ============================================================
# apps/tutoring/models.py
# ============================================================
 
"""
Xporadia — apps/tutoring/models.py
"""
import uuid
from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from apps.payments.models import Payment


class SessionMode(models.TextChoices):
    HOME          = "home",    "À domicile"
    TEACHER_PLACE = "teacher", "Chez l'enseignant"
    ONLINE        = "online",  "En ligne"
 
 
class TutoringSessionStatus(models.TextChoices):
    PENDING   = "pending",   "En attente"
    CONFIRMED = "confirmed", "Confirmée"
    ONGOING   = "ongoing",   "En cours"
    COMPLETED = "completed", "Terminée"
    CANCELLED = "cancelled", "Annulée"
    DISPUTED  = "disputed",  "En litige"
 
 
class TutoringSession(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                         related_name="tutoring_sessions_as_teacher",
                                         limit_choices_to={"primary_role": "teacher"})
    parent          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                         related_name="tutoring_sessions_as_parent",
                                         limit_choices_to={"primary_role": "parent"})
    child_name      = models.CharField(max_length=100)
    child_level     = models.CharField(max_length=50)
    subject         = models.CharField(max_length=50)
    mode            = models.CharField(max_length=10, choices=SessionMode.choices)
    date            = models.DateField()
    start_time      = models.TimeField()
    duration_min    = models.PositiveSmallIntegerField(default=60)
    address         = models.TextField(blank=True)
    note_for_teacher = models.TextField(max_length=300, blank=True)
    gross_amount    = models.PositiveIntegerField()
    commission_rate = models.DecimalField(max_digits=4, decimal_places=2, default=15)
    net_amount      = models.PositiveIntegerField(null=True, blank=True)
    escrow_released = models.BooleanField(default=False)
    released_at     = models.DateTimeField(null=True, blank=True)
    status          = models.CharField(max_length=15, choices=TutoringSessionStatus.choices,
                                        default=TutoringSessionStatus.PENDING)
    created_at      = models.DateTimeField(auto_now_add=True)
    confirmed_at    = models.DateTimeField(null=True, blank=True)
    cancelled_at    = models.DateTimeField(null=True, blank=True)
    cancel_reason   = models.TextField(blank=True)
    payments        = GenericRelation(
        Payment, content_type_field="content_type", object_id_field="object_id",
        related_query_name="tutoring_session",
    )

    class Meta:
        verbose_name        = "Séance de cours particulier"
        verbose_name_plural = "Séances de cours particuliers"
        ordering            = ["-date", "-start_time"]
        indexes             = [models.Index(fields=["teacher", "status"]),
                                models.Index(fields=["parent", "status"])]
 
    def save(self, *args, **kwargs):
        if self.gross_amount and self.commission_rate:
            self.net_amount = int(self.gross_amount * (1 - self.commission_rate / 100))
        super().save(*args, **kwargs)
 
    def __str__(self):
        return f"Cours {self.subject} — {self.child_name} — {self.date}"
 
 
class TutoringReview(models.Model):
    session      = models.ForeignKey(TutoringSession, on_delete=models.CASCADE,
                                      related_name="reviews")
    author       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="tutoring_reviews")
    author_type  = models.CharField(max_length=10,
                                     choices=[("parent","Parent"),("student","Élève")])
    rating       = models.PositiveSmallIntegerField()
    comment      = models.TextField(max_length=150, blank=True)
    is_moderated = models.BooleanField(default=False)
    teacher_reply = models.TextField(max_length=200, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Avis cours particulier"
        verbose_name_plural = "Avis cours particuliers"
        unique_together     = ("session", "author")
 
    def __str__(self):
        return f"Avis {self.rating}★ — {self.session}"
 
 
class TutoringSubscription(models.Model):
    """Abonnement récurrent parent/enseignant — la facturation périodique
    réelle (prélèvement Mobile Money automatique mensuel) suppose un
    ordonnanceur et des rappels d'échec de paiement hors de portée de ce
    build (EP-05 se concentre sur la réservation à la séance, payée et
    séquestrée immédiatement) : le modèle existe pour la donnée, mais
    aucune API n'y est encore rattachée."""

    parent      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="tutoring_subscriptions",
                                     limit_choices_to={"primary_role": "parent"})
    teacher     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="tutoring_subscriptions_as_teacher",
                                     limit_choices_to={"primary_role": "teacher"})
    subject     = models.CharField(max_length=50)
    child_name  = models.CharField(max_length=100)
    monthly_rate = models.PositiveIntegerField()
    is_active   = models.BooleanField(default=True)
    start_date  = models.DateField()
    end_date    = models.DateField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Abonnement cours"
        verbose_name_plural = "Abonnements cours"
        unique_together     = ("parent", "teacher", "subject")
 
    def __str__(self):
        return f"Abonnement {self.parent.get_full_name()} → {self.teacher.get_full_name()}"
 