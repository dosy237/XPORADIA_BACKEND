
# ============================================================
# apps/library/models.py
#
# Bibliothèque numérique d'un établissement — Story 4 du chantier
# "Classes". Chaque ressource appartient à l'établissement qui l'a
# publiée (cours, fiches, exercices, corrigés, annales), organisée par
# matière/niveau/type, et accessible à tout le personnel enseignant de
# cet établissement. L'accès élève/parent arrivera avec la Story 6
# (espace élève), une fois les comptes élèves définis.
# ============================================================

import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.users.models import DirectorProfile


class ResourceType(models.TextChoices):
    COURSE   = "course",   "Cours"
    REVISION = "revision", "Fiche de révision"
    EXERCISE = "exercise", "Exercice"
    SOLUTION = "solution", "Corrigé"
    EXAM     = "exam",     "Annale BEPC/BAC"


class ResourceCategory(models.TextChoices):
    """Rayon thématique — une classification de curiosité générale,
    distincte de `ResourceType` (qui reste un type pédagogique : cours,
    exercice, corrigé...). Le fonds actuel est entièrement scolaire, mais
    le champ couvre déjà les rayons plus larges prévus pour la
    bibliothèque, prêts à être peuplés."""

    ACADEMIC    = "academic",    "Scolaire"
    LITERATURE  = "literature",  "Littérature"
    SOCIETY     = "society",     "Société & anthropologie"
    SCIENCE     = "science",     "Sciences & vulgarisation"
    BIOGRAPHY   = "biography",   "Biographies & entrepreneuriat"
    ARTS        = "arts",        "Arts"
    ENVIRONMENT = "environment", "Environnement"


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
    establishment     = models.ForeignKey(DirectorProfile, on_delete=models.CASCADE,
                                           related_name="library_resources")
    title             = models.CharField(max_length=300)
    description       = models.TextField(max_length=500, blank=True)
    resource_type     = models.CharField(max_length=15, choices=ResourceType.choices)
    category          = models.CharField(max_length=20, choices=ResourceCategory.choices,
                                          default=ResourceCategory.ACADEMIC)
    level             = models.CharField(max_length=10, choices=SchoolLevel.choices)
    subject           = models.CharField(max_length=50)
    cover_image       = models.ImageField(upload_to="library_covers/", null=True, blank=True)
    # Coexistent : celui qui publie choisit l'un ou l'autre (jamais les
    # deux obligatoires), voir clean(). Un PDF hébergé chez nous s'ouvre
    # in-app ; un simple lien externe s'ouvre normalement.
    file_url          = models.URLField(blank=True)
    pdf_file          = models.FileField(upload_to="library_pdfs/", null=True, blank=True)
    file_size_kb      = models.PositiveIntegerField(default=0)
    tags              = models.JSONField(default=list, blank=True)
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
    # Toujours dérivé des ResourceRating individuelles (voir signals.py) —
    # jamais saisi à la main, pour ne jamais perdre la trace de qui a noté
    # quoi derrière une simple moyenne.
    avg_rating        = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    ratings_count     = models.PositiveIntegerField(default=0)
    is_archived       = models.BooleanField(default=False)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    def clean(self):
        if not self.file_url and not self.pdf_file:
            raise ValidationError("Renseignez un PDF hébergé ou un lien externe.")

    class Meta:
        verbose_name        = "Ressource bibliothèque"
        verbose_name_plural = "Ressources bibliothèque"
        ordering            = ["-created_at"]
        indexes             = [
            models.Index(fields=["establishment", "level", "subject", "resource_type"]),
            models.Index(fields=["moderation_status"]),
        ]

    def __str__(self):
        return f"[{self.level}][{self.subject}] {self.title} — {self.establishment.school_name}"


class ResourceRating(models.Model):
    """Note individuelle, traçable — un utilisateur note une ressource une
    fois (unique_together), peut la corriger ensuite. `LibraryResource.
    avg_rating`/`ratings_count` sont recalculés automatiquement depuis ces
    lignes (voir signals.py), jamais saisis à la main."""

    resource   = models.ForeignKey(LibraryResource, on_delete=models.CASCADE, related_name="ratings")
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name="library_ratings")
    score      = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("resource", "user")
        verbose_name = "Note"
        verbose_name_plural = "Notes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.get_full_name()} → {self.resource.title} : {self.score}/5"


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
