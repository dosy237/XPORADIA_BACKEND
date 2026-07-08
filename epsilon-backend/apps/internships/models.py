
# ============================================================
# apps/internships/models.py
# ============================================================
 
import uuid
from django.conf import settings
from django.db import models
 
 
class InternshipLevel(models.TextChoices):
    COLLEGE   = "3e",        "3ème"
    SECONDE   = "2nde",      "Seconde"
    PREMIERE  = "1ere",      "Première"
    TERMINALE = "terminale", "Terminale"
 
 
class InternshipOffer(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                        related_name="internship_offers",
                                        limit_choices_to={"primary_role": "company"})
    title          = models.CharField(max_length=200)
    domain         = models.CharField(max_length=100)
    missions       = models.TextField()
    level          = models.CharField(max_length=15, choices=InternshipLevel.choices)
    duration_weeks = models.PositiveSmallIntegerField()
    period_start   = models.DateField()
    period_end     = models.DateField()
    places         = models.PositiveSmallIntegerField(default=1)
    city           = models.CharField(max_length=100)
    skills_wanted  = models.JSONField(default=list)
    is_premium     = models.BooleanField(default=False)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Offre de stage"
        verbose_name_plural = "Offres de stage"
        ordering            = ["-is_premium", "-created_at"]
 
    def __str__(self):
        return f"{self.title} — {self.domain} ({self.level})"
 
 
class InternshipApplicationStatus(models.TextChoices):
    PENDING  = "pending",  "En attente"
    ACCEPTED = "accepted", "Acceptée"
    REJECTED = "rejected", "Refusée"
 
 
class InternshipApplication(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer         = models.ForeignKey(InternshipOffer, on_delete=models.CASCADE,
                                       related_name="applications")
    school        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                       related_name="internship_applications",
                                       limit_choices_to={"primary_role": "director"})
    student_name  = models.CharField(max_length=200)
    student_level = models.CharField(max_length=50)
    motivation    = models.TextField(max_length=600, blank=True)
    status        = models.CharField(max_length=10,
                                      choices=InternshipApplicationStatus.choices,
                                      default=InternshipApplicationStatus.PENDING)
    applied_at    = models.DateTimeField(auto_now_add=True)
    reviewed_at   = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        verbose_name        = "Candidature stage"
        verbose_name_plural = "Candidatures stage"
        ordering            = ["-applied_at"]
 
    def __str__(self):
        return f"{self.student_name} → {self.offer.title}"
 
 
class ConventionStatus(models.TextChoices):
    GENERATED  = "generated",  "Générée"
    SENT       = "sent",       "Envoyée"
    SIGNED_SCH = "signed_sch", "Signée école"
    SIGNED_ENT = "signed_ent", "Signée entreprise"
    COMPLETE   = "complete",   "Complète"
 
 
class InternshipConvention(models.Model):
    id                   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application          = models.OneToOneField(InternshipApplication,
                                                 on_delete=models.CASCADE,
                                                 related_name="convention")
    pdf_url              = models.URLField(blank=True)
    status               = models.CharField(max_length=15, choices=ConventionStatus.choices,
                                             default=ConventionStatus.GENERATED)
    signed_by_school_at  = models.DateTimeField(null=True, blank=True)
    signed_by_company_at = models.DateTimeField(null=True, blank=True)
    generated_at         = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Convention de stage"
        verbose_name_plural = "Conventions de stage"
 
    def __str__(self):
        return f"Convention — {self.application.student_name}"
 
 
class InternshipJournal(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    convention = models.ForeignKey(InternshipConvention, on_delete=models.CASCADE,
                                    related_name="journal_entries")
    date       = models.DateField()
    content    = models.TextField()
    photos     = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Journal de stage"
        verbose_name_plural = "Journaux de stage"
        unique_together     = ("convention", "date")
        ordering            = ["date"]
 
    def __str__(self):
        return f"Journal {self.convention.application.student_name} — {self.date}"
 
 
class EvaluatorType(models.TextChoices):
    COMPANY = "company", "Entreprise → Stagiaire"
    STUDENT = "student", "Stagiaire → Entreprise"
 
 
class InternshipEvaluation(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    convention     = models.ForeignKey(InternshipConvention, on_delete=models.CASCADE,
                                        related_name="evaluations")
    evaluator_type = models.CharField(max_length=10, choices=EvaluatorType.choices)
    punctuality    = models.PositiveSmallIntegerField(null=True, blank=True)
    initiative     = models.PositiveSmallIntegerField(null=True, blank=True)
    integration    = models.PositiveSmallIntegerField(null=True, blank=True)
    skills         = models.PositiveSmallIntegerField(null=True, blank=True)
    global_rating  = models.PositiveSmallIntegerField(null=True, blank=True)
    comment        = models.TextField(max_length=500, blank=True)
    attestation_url = models.URLField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Évaluation stage"
        verbose_name_plural = "Évaluations stage"
        unique_together     = ("convention", "evaluator_type")
 
    def __str__(self):
        return f"Éval {self.evaluator_type} — {self.convention.application.student_name}"