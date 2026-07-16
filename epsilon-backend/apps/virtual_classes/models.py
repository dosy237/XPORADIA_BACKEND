# ============================================================
# apps/virtual_classes/models.py
#
# Espace numérique d'une matière (cours, exercices) — Story 3 du chantier
# "Classes". Rattaché 1:1 à une apps.academics.Subject, créé automatiquement
# à la création de celle-ci (voir signals.py).
#
# Story 6 ("espace élève personnel") : il n'existe toujours aucun compte
# élève propre — l'accès reste médié par le parent, qui soumet un devoir
# "au nom de" son ENFANT (Child), exactement comme il candidate à un stage
# en son nom (Epic A) ou l'inscrit dans une classe (Story 5). Voir Submission.
# ============================================================

import uuid

from django.conf import settings
from django.db import models

from apps.academics.models import Subject
from apps.users.models import Child


class VirtualClass(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.OneToOneField(Subject, on_delete=models.CASCADE, related_name="virtual_class")
    description = models.TextField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Espace numérique de matière"
        verbose_name_plural = "Espaces numériques de matière"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Espace numérique — {self.subject}"

    @property
    def teacher(self):
        return self.subject.teacher


class ExerciseStatus(models.TextChoices):
    DRAFT = "draft", "Brouillon"
    PUBLISHED = "published", "Publié"
    CLOSED = "closed", "Clôturé"


class Exercise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    virtual_class = models.ForeignKey(VirtualClass, on_delete=models.CASCADE, related_name="exercises")
    title = models.CharField(max_length=200)
    instructions = models.TextField()
    attachments = models.JSONField(default=list, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=ExerciseStatus.choices, default=ExerciseStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cours / exercice"
        verbose_name_plural = "Cours / exercices"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.virtual_class}"


class SubmissionStatus(models.TextChoices):
    SUBMITTED = "submitted", "Soumis"
    GRADED    = "graded",    "Corrigé"


class Submission(models.Model):
    """Copie rendue par un parent au nom de son enfant pour un Exercise —
    notée sur 20 (convention scolaire ivoirienne), par l'enseignant dédié
    de la matière."""

    exercise      = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="submissions")
    child         = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="submissions")
    submitted_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions_made"
    )
    content       = models.TextField(blank=True)
    attachments   = models.JSONField(default=list, blank=True)
    status        = models.CharField(max_length=15, choices=SubmissionStatus.choices, default=SubmissionStatus.SUBMITTED)
    grade         = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, help_text="Note sur 20")
    feedback      = models.TextField(blank=True)
    submitted_at  = models.DateTimeField(auto_now_add=True)
    graded_at     = models.DateTimeField(null=True, blank=True)
    graded_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="graded_submissions",
    )

    class Meta:
        verbose_name        = "Soumission"
        verbose_name_plural = "Soumissions"
        unique_together     = ("exercise", "child")
        ordering            = ["-submitted_at"]

    def __str__(self):
        return f"{self.child.first_name} → {self.exercise.title} ({self.status})"
