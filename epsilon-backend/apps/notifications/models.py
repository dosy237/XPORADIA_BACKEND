"""
Xporadia — apps/notifications/models.py
Entité : Notification (multi-canal)
"""
import uuid
from django.conf import settings
from django.db import models


class NotificationType(models.TextChoices):
    NEW_JOB_OFFER      = "new_job_offer",      "Nouvelle offre d'emploi"
    APPLICATION_VIEWED = "application_viewed", "Candidature consultée"
    EXAM_AVAILABLE     = "exam_available",     "Examen disponible"
    EXAM_RESULT        = "exam_result",        "Résultat d'examen"
    SESSION_CONFIRMED  = "session_confirmed",  "Séance confirmée"
    SESSION_CANCELLED  = "session_cancelled",  "Séance annulée"
    PAYMENT_RECEIVED   = "payment_received",   "Paiement reçu"
    CERT_EXPIRY        = "cert_expiry",        "Alerte expiration certification"
    NEW_MESSAGE        = "new_message",        "Nouveau message"
    EXERCISE_PUBLISHED = "exercise_published", "Devoir publié"
    EXERCISE_SUBMITTED = "exercise_submitted", "Copie soumise"
    CORRECTION_READY   = "correction_ready",   "Correction disponible"
    RECRUITMENT        = "recruitment",        "Recrutement confirmé"
    STAGE_UPDATE       = "stage_update",       "Mise à jour stage"
    CLASS_ASSIGNMENT   = "class_assignment",   "Affectation à une matière"
    ENROLLMENT_UPDATE  = "enrollment_update",  "Mise à jour de scolarité"
    SYSTEM             = "system",             "Système"


class NotificationChannel(models.TextChoices):
    PUSH  = "push",  "Push mobile"
    SMS   = "sms",   "SMS"
    EMAIL = "email", "Email"
    INAPP = "inapp", "In-app"


class Notification(models.Model):
    """
    Notification multi-canal envoyée à un utilisateur.
    Un même événement peut générer plusieurs Notification
    (une par canal : push + email par exemple).
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    on_delete=models.CASCADE,
                    related_name="notifications"
                 )
    notif_type = models.CharField(
                    max_length=30,
                    choices=NotificationType.choices
                 )
    channel    = models.CharField(
                    max_length=10,
                    choices=NotificationChannel.choices,
                    default=NotificationChannel.INAPP
                 )
    title      = models.CharField(max_length=150)
    body       = models.TextField()
    data       = models.JSONField(
                    default=dict,
                    help_text="Payload extra — ex: {url, object_id, object_type}"
                 )
    is_read    = models.BooleanField(default=False)
    read_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Notification"
        verbose_name_plural = "Notifications"
        ordering            = ["-created_at"]
        indexes             = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "notif_type"]),
        ]

    def __str__(self):
        statut = "lu" if self.is_read else "non lu"
        return f"[{self.notif_type}] → {self.user.get_full_name()} ({statut})"


class DevicePlatform(models.TextChoices):
    IOS = "ios", "iOS"
    ANDROID = "android", "Android"
    WEB = "web", "Web"


class DeviceToken(models.Model):
    """Token push Expo d'un appareil. Un utilisateur peut avoir plusieurs
    appareils enregistrés (téléphone + tablette, réinstallation...). Le
    token appartient à l'appareil, pas au compte : à la reconnexion d'un
    autre utilisateur sur le même appareil, il est simplement réassigné."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_tokens"
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=10, choices=DevicePlatform.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Token push"
        verbose_name_plural = "Tokens push"

    def __str__(self):
        return f"{self.token[:24]}... — {self.user.get_full_name()}"