# ============================================================
# apps/virtual_classes/models.py
#
# Espace numérique d'une matière (cours, exercices) — Story 3 du chantier
# "Classes". Rattaché 1:1 à une apps.academics.Subject, créé automatiquement
# à la création de celle-ci (voir signals.py).
#
# La soumission et la correction par l'élève ne sont pas construites ici :
# le système n'a aujourd'hui aucun compte élève (seulement des ENFANT
# rattachés à un parent, sans connexion propre). Cette brique arrivera
# avec la Story 6 ("espace élève personnel"), une fois ce modèle d'accès
# tranché — construire une Submission maintenant serait une hypothèse
# prématurée sur cette conception.
# ============================================================

import uuid

from django.db import models

from apps.academics.models import Subject


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
