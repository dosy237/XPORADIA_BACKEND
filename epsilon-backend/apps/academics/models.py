"""
Xporadia — apps/academics/models.py

Structure académique d'un établissement (privé, du primaire au supérieur) :
Département → Filière → Classe → Matière, avec un enseignant titulaire par
classe et un enseignant dédié par matière.

Stories 1 et 2 du chantier "Classes". Le contenu pédagogique (Story 3), la
bibliothèque (Story 4), les effectifs annuels (Story 5) et l'espace élève
(Story 6) sont des stories séparées, pas encore construites ici.
"""
import secrets

from django.conf import settings
from django.db import models

from apps.users.models import DirectorProfile


class Department(models.Model):
    """Département d'un établissement — ex: "Primaire", "Secondaire",
    "Sciences et Technologies". Le découpage est libre : un établissement
    primaire peut n'avoir qu'un seul département générique."""

    establishment = models.ForeignKey(
        DirectorProfile, on_delete=models.CASCADE, related_name="departments"
    )
    name = models.CharField(max_length=200, verbose_name="Nom du département")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Département"
        verbose_name_plural = "Départements"
        unique_together = ("establishment", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.establishment.school_name}"


class Track(models.Model):
    """Filière au sein d'un département — ex: "Scientifique", "Littéraire",
    "Génie Informatique". Pour un établissement sans filières distinctes
    (primaire), une seule filière générique suffit."""

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=200, verbose_name="Nom de la filière")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Filière"
        verbose_name_plural = "Filières"
        unique_together = ("department", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.department.name})"


class SchoolClass(models.Model):
    """Classe au sein d'une filière, pour une année scolaire donnée — ex:
    "Terminale D1", "CM2 A". L'enseignant titulaire est affecté par
    l'établissement et sera responsable de la classe (création des
    matières, réception des notes des enseignants dédiés — stories
    suivantes)."""

    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=100, verbose_name="Nom de la classe")
    school_year = models.CharField(
        max_length=9, verbose_name="Année scolaire", help_text="Ex : 2025-2026"
    )
    homeroom_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homeroom_classes",
        limit_choices_to={"primary_role": "teacher"},
        verbose_name="Enseignant titulaire",
    )
    capacity = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Effectif maximum")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Classe"
        verbose_name_plural = "Classes"
        unique_together = ("track", "name", "school_year")
        ordering = ["-school_year", "name"]

    def __str__(self):
        return f"{self.name} — {self.school_year} ({self.track.name})"


class Subject(models.Model):
    """Matière enseignée au sein d'une classe — ex: "Mathématiques",
    "Physique-Chimie". Créée par l'enseignant titulaire de la classe, qui
    y affecte un enseignant dédié (Story 2 du chantier "Classes"). Le
    contenu pédagogique (cours, exercices, corrections, notes — Story 3)
    se rattache à cette matière."""

    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150, verbose_name="Nom de la matière")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dedicated_subjects",
        limit_choices_to={"primary_role": "teacher"},
        verbose_name="Enseignant dédié",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Matière"
        verbose_name_plural = "Matières"
        unique_together = ("school_class", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.school_class}"


class TeacherInvitation(models.Model):
    """Invitation envoyée par email à un enseignant sans compte Xporadia
    encore actif, pour devenir l'enseignant dédié d'une Matière. Le lien
    contenu dans l'email amène la personne à créer son compte (ou à se
    connecter si elle en a déjà un) puis rattache automatiquement son
    compte à la matière une fois acceptée."""

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(verbose_name="Email invité")
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_teacher_invitations"
    )
    token = models.CharField(max_length=43, unique=True, editable=False)
    is_accepted = models.BooleanField(default=False)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Invitation enseignant"
        verbose_name_plural = "Invitations enseignant"
        unique_together = ("subject", "email")
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    def __str__(self):
        statut = "acceptée" if self.is_accepted else "en attente"
        return f"Invitation {self.email} → {self.subject} ({statut})"
