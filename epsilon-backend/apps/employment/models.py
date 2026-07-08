 
# ============================================================
# apps/employment/models.py
# ============================================================
 
"""
Xporadia — apps/employment/models.py
"""
import uuid
from django.conf import settings
from django.db import models
from apps.certification.models import CertificationLevel
 
 
class ContractType(models.TextChoices):
    CDI      = "cdi",      "CDI"
    CDD      = "cdd",      "CDD"
    VACATION = "vacation", "Vacation"
    INTERIM  = "interim",  "Intérim"
 
 
class JobStatus(models.TextChoices):
    DRAFT    = "draft",    "Brouillon"
    PENDING  = "pending",  "En attente de modération"
    ACTIVE   = "active",   "Active"
    CLOSED   = "closed",   "Clôturée"
    EXPIRED  = "expired",  "Expirée"
 
 
class ApplicationStatus(models.TextChoices):
    PENDING    = "pending",    "En attente"
    VIEWED     = "viewed",     "Vue"
    INTERVIEW  = "interview",  "Entretien"
    ACCEPTED   = "accepted",   "Acceptée"
    REJECTED   = "rejected",   "Refusée"
    WITHDRAWN  = "withdrawn",  "Retirée"
 
 
class JobListing(models.Model):
    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school             = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                            related_name="job_listings",
                                            limit_choices_to={"primary_role": "director"})
    title              = models.CharField(max_length=200)
    subject            = models.CharField(max_length=50)
    levels             = models.JSONField(default=list)
    contract_type      = models.CharField(max_length=15, choices=ContractType.choices)
    salary_min         = models.PositiveIntegerField(null=True, blank=True)
    salary_max         = models.PositiveIntegerField(null=True, blank=True)
    cert_level_required = models.CharField(max_length=10, choices=CertificationLevel.choices,
                                            default=CertificationLevel.BRONZE)
    description        = models.TextField()
    city               = models.CharField(max_length=100)
    commune            = models.CharField(max_length=100, blank=True)
    start_date         = models.DateField(null=True, blank=True)
    status             = models.CharField(max_length=10, choices=JobStatus.choices,
                                           default=JobStatus.PENDING)
    published_at       = models.DateTimeField(null=True, blank=True)
    expires_at         = models.DateField(null=True, blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name        = "Offre d'emploi"
        verbose_name_plural = "Offres d'emploi"
        ordering            = ["-created_at"]
        indexes             = [models.Index(fields=["status"]),
                                models.Index(fields=["subject", "city"])]
 
    def __str__(self):
        return f"{self.title}"
 
 
class JobApplication(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                          related_name="job_applications",
                                          limit_choices_to={"primary_role": "teacher"})
    listing          = models.ForeignKey(JobListing, on_delete=models.CASCADE,
                                          related_name="applications")
    cover_letter     = models.TextField(max_length=500, blank=True)
    status           = models.CharField(max_length=15, choices=ApplicationStatus.choices,
                                         default=ApplicationStatus.PENDING)
    applied_at       = models.DateTimeField(auto_now_add=True)
    viewed_at        = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
 
    class Meta:
        verbose_name        = "Candidature"
        verbose_name_plural = "Candidatures"
        unique_together     = ("teacher", "listing")
        ordering            = ["-applied_at"]
 
    def __str__(self):
        return f"{self.teacher.get_full_name()} → {self.listing.title}"
 
 
class PaymentStatus(models.TextChoices):
    PENDING  = "pending",  "En attente"
    PAID     = "paid",     "Payée"
    FAILED   = "failed",   "Échouée"
    WAIVED   = "waived",   "Dispensée"
 
 
class Recruitment(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                           related_name="recruitments_as_school",
                                           limit_choices_to={"primary_role": "director"})
    teacher           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                           related_name="recruitments_as_teacher",
                                           limit_choices_to={"primary_role": "teacher"})
    application       = models.OneToOneField(JobApplication, on_delete=models.SET_NULL,
                                              null=True, blank=True)
    salary_agreed     = models.PositiveIntegerField()
    commission_rate   = models.DecimalField(max_digits=4, decimal_places=2, default=10)
    commission_amount = models.PositiveIntegerField(null=True, blank=True)
    payment_status    = models.CharField(max_length=10, choices=PaymentStatus.choices,
                                          default=PaymentStatus.PENDING)
    attestation_url   = models.URLField(blank=True)
    confirmed_at      = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Recrutement"
        verbose_name_plural = "Recrutements"
        ordering            = ["-confirmed_at"]
 
    def save(self, *args, **kwargs):
        if self.salary_agreed and self.commission_rate:
            self.commission_amount = int(self.salary_agreed * self.commission_rate / 100)
        super().save(*args, **kwargs)
 
    def __str__(self):
        return f"Recrutement {self.teacher.get_full_name()}"
 
 
class EmployerReview(models.Model):
    recruitment        = models.OneToOneField(Recruitment, on_delete=models.CASCADE,
                                               related_name="employer_review")
    atmosphere         = models.PositiveSmallIntegerField()
    contract_respect   = models.PositiveSmallIntegerField()
    working_conditions = models.PositiveSmallIntegerField()
    payment_timeliness = models.PositiveSmallIntegerField()
    comment            = models.TextField(max_length=500, blank=True)
    is_moderated       = models.BooleanField(default=False)
    created_at         = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        verbose_name        = "Avis employeur"
        verbose_name_plural = "Avis employeurs"
 
    def average_rating(self):
        scores = [self.atmosphere, self.contract_respect,
                  self.working_conditions, self.payment_timeliness]
        return round(sum(scores) / len(scores), 2)
 
 