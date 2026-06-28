
# ============================================================
# apps/admin_xporadia/models.py
# ============================================================
 
import uuid
from django.conf import settings
from django.db import models
 
 
class Etablissement(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    directeur         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                           related_name="etablissements",
                                           limit_choices_to={"primary_role": "director"})
    nom               = models.CharField(max_length=200)
    adresse           = models.TextField()
    ville             = models.CharField(max_length=100)
    commune           = models.CharField(max_length=100, blank=True)
    telephone         = models.CharField(max_length=20, blank=True)
    email             = models.EmailField(blank=True)
    niveaux_enseignes = models.JSONField(default=list)
    capacite_eleves   = models.PositiveIntegerField(default=0)
    docs_legaux       = models.JSONField(default=list)
    is_partenaire     = models.BooleanField(default=False)
    score_label       = models.PositiveSmallIntegerField(default=0)
    label_obtained_at = models.DateField(null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Établissement"
        verbose_name_plural = "Établissements"
        ordering            = ["nom"]
 
    def __str__(self):
        return f"{self.nom} — {self.ville}"
 
 
class Filiere(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    etablissement = models.ForeignKey(Etablissement, on_delete=models.CASCADE,
                                       related_name="filieres")
    nom           = models.CharField(max_length=100)
    code          = models.CharField(max_length=10, blank=True)
    description   = models.TextField(blank=True)
 
    class Meta:
        verbose_name        = "Filière"
        verbose_name_plural = "Filières"
        unique_together     = ("etablissement", "code")
        ordering            = ["etablissement", "code"]
 
    def __str__(self):
        return f"{self.etablissement.nom} — Filière {self.nom}"
 
 
class Classe(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filiere        = models.ForeignKey(Filiere, on_delete=models.CASCADE,
                                        related_name="classes")
    nom            = models.CharField(max_length=50)
    niveau         = models.CharField(max_length=20)
    effectif       = models.PositiveSmallIntegerField(default=0)
    annee_scolaire = models.CharField(max_length=10, default="2024-2025")
 
    class Meta:
        verbose_name        = "Classe"
        verbose_name_plural = "Classes"
        unique_together     = ("filiere", "nom", "annee_scolaire")
        ordering            = ["filiere", "niveau", "nom"]
 
    def __str__(self):
        return f"{self.nom} — {self.filiere.etablissement.nom}"
 
 
class Matiere(models.Model):
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom  = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    icon = models.CharField(max_length=50, blank=True)
 
    class Meta:
        verbose_name        = "Matière"
        verbose_name_plural = "Matières"
        ordering            = ["nom"]
 
    def __str__(self):
        return self.nom
 
 
class ClasseMatiere(models.Model):
    classe            = models.ForeignKey(Classe, on_delete=models.CASCADE,
                                           related_name="matieres")
    matiere           = models.ForeignKey(Matiere, on_delete=models.CASCADE,
                                           related_name="classes")
    enseignant        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                           null=True, blank=True,
                                           related_name="classes_enseignees",
                                           limit_choices_to={"primary_role": "teacher"})
    nb_heures_semaine = models.PositiveSmallIntegerField(default=2)
 
    class Meta:
        verbose_name        = "Matière de classe"
        verbose_name_plural = "Matières de classes"
        unique_together     = ("classe", "matiere")
 
    def __str__(self):
        teacher = self.enseignant.get_full_name() if self.enseignant else "Non affecté"
        return f"{self.classe.nom} — {self.matiere.nom} → {teacher}"
 
 
class AuditLog(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name="audit_logs")
    action     = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    object_id  = models.CharField(max_length=100, blank=True)
    old_value  = models.JSONField(null=True, blank=True)
    new_value  = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp  = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Log d'audit"
        verbose_name_plural = "Logs d'audit"
        ordering            = ["-timestamp"]
        indexes             = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["user", "timestamp"]),
        ]
        default_permissions = ("add", "view")
 
    def __str__(self):
        return f"[{self.timestamp}] {self.action} — {self.model_name}#{self.object_id}"