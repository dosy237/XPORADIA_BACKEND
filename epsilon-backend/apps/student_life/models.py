"""
Xporadia — apps/student_life/models.py

Espace personnel de l'élève, hors messagerie et hors devoirs (déjà couverts
par apps.messaging et apps.virtual_classes) : notes de révision, documents
importés, et le module "Vie & objectifs" — fondation légère pensée pour un
futur assistant IA (voir related_subjects sur LifeGoal) sans que cette
promesse soit tenue aujourd'hui.

Tout est rattaché à Child (pas User) — cohérent avec le reste de la
plateforme : l'historique appartient à l'élève même avant l'activation de
son propre compte (un parent peut, par exemple, avoir commencé à noter les
objectifs de son enfant plus jeune — même s'il n'y a aujourd'hui pas
d'écriture côté parent, la donnée reste portée par Child pour rester
cohérente avec Submission, Enrollment, etc.).
"""
from django.conf import settings
from django.db import models

from apps.users.models import Child


class PersonalNote(models.Model):
    """Note de révision — liée à une matière pour resurgir au bon moment
    (rappel de révision avant le prochain cours), ou libre."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="personal_notes")
    subject = models.ForeignKey(
        "academics.Subject", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    attachments = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Note personnelle"
        verbose_name_plural = "Notes personnelles"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title} — {self.child.first_name}"


class PersonalDocument(models.Model):
    """Document importé (PDF de cours scanné ailleurs, etc.) — juste un
    nom et un fichier, pas de traitement particulier."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="personal_documents")
    name = models.CharField(max_length=200, verbose_name="Nom du document")
    file = models.FileField(upload_to="student_documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Document personnel"
        verbose_name_plural = "Documents personnels"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.name} — {self.child.first_name}"


class LifeGoal(models.Model):
    """Ce que l'élève veut faire de sa vie — texte libre, pas de liste
    fermée de métiers pour ne pas l'enfermer dans des cases."""

    child = models.OneToOneField(Child, on_delete=models.CASCADE, related_name="life_goal")
    description = models.TextField(blank=True, verbose_name="Ce que je veux faire de ma vie")
    # Liste de matières (texte libre) que l'élève associe lui-même à son
    # objectif — support de données pour un futur module de recommandation
    # IA, pas encore exploité côté produit aujourd'hui.
    related_subjects = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Objectif de vie"
        verbose_name_plural = "Objectifs de vie"

    def __str__(self):
        return f"Objectif de {self.child.first_name}"


class BucketListItem(models.Model):
    """Ce que l'élève veut avoir accompli — coché au fur et à mesure."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="bucket_list_items")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_done = models.BooleanField(default=False)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Objectif (bucket list)"
        verbose_name_plural = "Objectifs (bucket list)"
        ordering = ["is_done", "due_date", "-created_at"]

    def __str__(self):
        statut = "fait" if self.is_done else "à faire"
        return f"{self.title} ({statut})"
