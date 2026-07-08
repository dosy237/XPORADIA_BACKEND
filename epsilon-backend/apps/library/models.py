 
# ============================================================
# apps/library/models.py
# ============================================================
 
import uuid
from django.conf import settings
from django.db import models
 
 
class ResourceType(models.TextChoices):
    COURSE   = "course",   "Cours"
    REVISION = "revision", "Fiche de révision"
    EXERCISE = "exercise", "Exercice"
    SOLUTION = "solution", "Corrigé"
    EXAM     = "exam",     "Annale BEPC/BAC"
 
 
class SchoolLevel(models.TextChoices):
    SIXIEME   = "6e",   "6ème"
    CINQUIEME = "5e",   "5ème"
    QUATRIEME = "4e",   "4ème"
    TROISIEME = "3e",   "3ème"
    SECONDE   = "2nde", "Seconde"
    PREMIERE  = "1ere", "Première"
    TERMINALE = "tle",  "Terminale"
 
 
class ModerationStatus(models.TextChoices):
    PENDING  = "pending",  "En attente"
    APPROVED = "approved", "Approuvée"
    REJECTED = "rejected", "Rejetée"
 
 
class LibraryResource(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title             = models.CharField(max_length=300)
    description       = models.TextField(max_length=500, blank=True)
    resource_type     = models.CharField(max_length=15, choices=ResourceType.choices)
    level             = models.CharField(max_length=10, choices=SchoolLevel.choices)
    subject           = models.CharField(max_length=50)
    file_url          = models.URLField()
    file_size_kb      = models.PositiveIntegerField(default=0)
    tags              = models.JSONField(default=list)
    author            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                           null=True, blank=True,
                                           related_name="library_contributions")
    is_contributed    = models.BooleanField(default=False)
    moderation_status = models.CharField(max_length=10, choices=ModerationStatus.choices,
                                          default=ModerationStatus.APPROVED)
    moderated_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                           null=True, blank=True,
                                           related_name="moderated_resources")
    moderated_at      = models.DateTimeField(null=True, blank=True)
    download_count    = models.PositiveIntegerField(default=0)
    avg_rating        = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    is_archived       = models.BooleanField(default=False)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Ressource bibliothèque"
        verbose_name_plural = "Ressources bibliothèque"
        ordering            = ["-created_at"]
        indexes             = [
            models.Index(fields=["level", "subject", "resource_type"]),
            models.Index(fields=["moderation_status"]),
        ]
 
    def __str__(self):
        return f"[{self.level}][{self.subject}] {self.title}"
 
 
class ResourceDownload(models.Model):
    resource      = models.ForeignKey(LibraryResource, on_delete=models.CASCADE,
                                       related_name="downloads")
    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                       related_name="resource_downloads")
    downloaded_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name = "Téléchargement"
        ordering     = ["-downloaded_at"]
 
    def __str__(self):
        return f"{self.user.get_full_name()} → {self.resource.title}"
 
 
class ResourceFavorite(models.Model):
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="resource_favorites")
    resource  = models.ForeignKey(LibraryResource, on_delete=models.CASCADE,
                                   related_name="favorited_by")
    list_name = models.CharField(max_length=100, default="Mes favoris")
    added_at  = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        unique_together = ("user", "resource", "list_name")
        verbose_name    = "Favori"
 
    def __str__(self):
        return f"{self.user.get_full_name()} ♥ {self.resource.title}"
 