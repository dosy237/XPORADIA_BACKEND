
 
# ============================================================
# apps/payments/models.py
# ============================================================
 
import uuid
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
 
 
class MobileOperator(models.TextChoices):
    ORANGE = "orange", "Orange Money CI"
    WAVE   = "wave",   "Wave"
    MTN    = "mtn",    "MTN MoMo"
 
 
class PaymentStatus(models.TextChoices):
    PENDING   = "pending",   "En attente"
    ESCROW    = "escrow",    "Séquestré"
    COMPLETED = "completed", "Complété"
    FAILED    = "failed",    "Échoué"
    REFUNDED  = "refunded",  "Remboursé"
    CANCELLED = "cancelled", "Annulé"
 
 
class PaymentType(models.TextChoices):
    TRAINING     = "training",     "Formation"
    TUTORING     = "tutoring",     "Cours particulier"
    SUBSCRIPTION = "subscription", "Abonnement directeur"
    COMMISSION   = "commission",   "Commission recrutement"
    RETAKE_FEE   = "retake_fee",   "Frais de rattrapage"
 
 
class Payment(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                        related_name="payments")
    amount         = models.PositiveIntegerField(help_text="FCFA")
    currency       = models.CharField(max_length=5, default="XOF")
    operator       = models.CharField(max_length=10, choices=MobileOperator.choices)
    phone_number   = models.CharField(max_length=20)
    tx_ref         = models.CharField(max_length=100, unique=True)
    operator_tx_id = models.CharField(max_length=100, blank=True)
    status         = models.CharField(max_length=15, choices=PaymentStatus.choices,
                                       default=PaymentStatus.PENDING)
    payment_type   = models.CharField(max_length=20, choices=PaymentType.choices)
    # Lien polymorphique
    content_type   = models.ForeignKey(ContentType, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    object_id      = models.UUIDField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")
    created_at     = models.DateTimeField(auto_now_add=True)
    completed_at   = models.DateTimeField(null=True, blank=True)
    webhook_data   = models.JSONField(default=dict)
 
    class Meta:
        verbose_name        = "Paiement"
        verbose_name_plural = "Paiements"
        ordering            = ["-created_at"]
        indexes             = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["tx_ref"]),
        ]
 
    def __str__(self):
        return f"{self.amount} XOF — {self.operator} — {self.status}"
 
 
class Reversal(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="reversals")
    payment      = models.ForeignKey(Payment, on_delete=models.CASCADE,
                                      related_name="reversals")
    amount       = models.PositiveIntegerField()
    operator     = models.CharField(max_length=10, choices=MobileOperator.choices)
    phone_number = models.CharField(max_length=20)
    status       = models.CharField(max_length=15,
                                     choices=[("pending","En attente"),
                                              ("sent","Envoyé"),
                                              ("failed","Échoué")],
                                     default="pending")
    reversed_at  = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Reversement"
        verbose_name_plural = "Reversements"
        ordering            = ["-created_at"]
 
    def __str__(self):
        return f"Reversement {self.amount} XOF → {self.teacher.get_full_name()}"
 
 
class DisputeStatus(models.TextChoices):
    OPEN     = "open",     "Ouvert"
    REVIEWED = "reviewed", "En révision"
    RESOLVED = "resolved", "Résolu"
    CLOSED   = "closed",   "Clôturé"
 
 
class Dispute(models.Model):
    payment     = models.ForeignKey(Payment, on_delete=models.CASCADE,
                                     related_name="disputes")
    opened_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="opened_disputes")
    reason      = models.TextField()
    status      = models.CharField(max_length=10, choices=DisputeStatus.choices,
                                    default=DisputeStatus.OPEN)
    resolution  = models.TextField(blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True,
                                     related_name="resolved_disputes")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Litige"
        verbose_name_plural = "Litiges"
        ordering            = ["-created_at"]
 
    def __str__(self):
        return f"Litige {self.status} — {self.payment}"
 