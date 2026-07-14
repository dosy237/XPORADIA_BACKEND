"""
Xporadia — apps/academics/models.py

Structure académique d'un établissement (privé, du primaire au supérieur) :
Département → Filière → Classe, avec un enseignant titulaire par classe.

Story 1 du chantier "Classes" — volontairement limitée à cette hiérarchie.
Les matières (Story 2), le contenu pédagogique (Story 3), la bibliothèque
(Story 4), les effectifs annuels (Story 5) et l'espace élève (Story 6)
sont des stories séparées, pas encore construites ici.
"""
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
