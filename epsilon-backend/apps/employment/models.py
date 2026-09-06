
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
    levels             = models.JSONField(default=list, blank=True)
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
                                           default=JobStatus.DRAFT)
    # Ciblage optionnel de profils "open to work" à la publication — ils
    # sont notifiés directement, l'offre reste par ailleurs visible de tous.
    targeted_teachers  = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True,
                                                 related_name="targeted_job_listings")
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
    # Figé à la confirmation (indépendant de application, qui peut devenir
    # nulle) — détermine tout le mode de paie : CDI = salaire fixe mensuel
    # (salary_agreed), tout le reste (CDD/Vacation/Intérim) = heures
    # déclarées et validées, payées au tarif horaire ci-dessous.
    contract_type     = models.CharField(max_length=10, choices=ContractType.choices, default=ContractType.CDI)
    salary_agreed     = models.PositiveIntegerField(
        null=True, blank=True, help_text="Salaire mensuel — uniquement pertinent pour un CDI"
    )
    # Xporadia est l'employeur intermédiaire : l'enseignant est payé à
    # hourly_rate_teacher par heure validée, l'établissement est facturé à
    # hourly_rate_billed par heure — l'écart est la marge Xporadia (même
    # mécanique que l'ancien séquestre des cours particuliers, rejouée ici
    # dans un contexte salarial). Nuls pour un CDI (salaire fixe).
    hourly_rate_teacher = models.PositiveIntegerField(null=True, blank=True, help_text="FCFA/heure versés à l'enseignant")
    hourly_rate_billed  = models.PositiveIntegerField(null=True, blank=True, help_text="FCFA/heure facturés à l'établissement")
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

    @property
    def requires_declared_hours(self) -> bool:
        return self.contract_type != ContractType.CDI

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


class JobSeekingRequest(models.Model):
    """Demande d'emploi publiée par un enseignant — privilège réservé à
    ceux ayant atteint le niveau de certification Or (voir
    apps.certification.MyCertificationStatusSerializer)."""

    teacher    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name="job_seeking_requests",
                                    limit_choices_to={"primary_role": "teacher"})
    subjects   = models.JSONField(default=list, blank=True)
    city       = models.CharField(max_length=100, blank=True)
    message    = models.TextField(max_length=500, blank=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Demande d'emploi"
        verbose_name_plural = "Demandes d'emploi"
        ordering            = ["-created_at"]

    def __str__(self):
        return f"Demande d'emploi — {self.teacher.get_full_name()}"


class WorkedHoursStatus(models.TextChoices):
    PENDING  = "pending",  "En attente de validation"
    APPROVED = "approved", "Validée"
    REJECTED = "rejected", "Rejetée"


class WorkedHours(models.Model):
    """Déclaration d'heures travaillées par un enseignant, rattachée à un
    recrutement confirmé (jamais dans le vide). Xporadia étant l'employeur
    intermédiaire (pas l'établissement), c'est la validation du directeur
    qui rend une déclaration comptable — sans validation, aucune heure
    n'entre dans la paie de fin de mois. Uniquement pertinent pour un
    contrat autre que CDI (voir Recruitment.requires_declared_hours)."""

    recruitment = models.ForeignKey(Recruitment, on_delete=models.CASCADE, related_name="worked_hours")
    date        = models.DateField()
    hours       = models.DecimalField(max_digits=4, decimal_places=2)
    note        = models.CharField(max_length=200, blank=True)
    status      = models.CharField(max_length=10, choices=WorkedHoursStatus.choices, default=WorkedHoursStatus.PENDING)
    declared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=200, blank=True)
    # Renseigné une fois la déclaration intégrée à une paie mensuelle —
    # empêche de compter deux fois les mêmes heures sur deux clôtures.
    payroll_entry = models.ForeignKey(
        "PayrollEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="worked_hours"
    )

    class Meta:
        verbose_name        = "Heures travaillées"
        verbose_name_plural = "Heures travaillées"
        ordering            = ["-date"]
        unique_together     = ("recruitment", "date")

    def __str__(self):
        return f"{self.recruitment.teacher.get_full_name()} — {self.date} ({self.hours}h, {self.status})"


class PayrollEntry(models.Model):
    """Une ligne de paie mensuelle pour un enseignant sur un recrutement
    donné — générée automatiquement à la clôture du mois (voir la commande
    run_monthly_payroll), à partir des seules heures VALIDÉES du mois.
    C'est cette entrée qui crédite le portefeuille de l'enseignant."""

    recruitment    = models.ForeignKey(Recruitment, on_delete=models.CASCADE, related_name="payroll_entries")
    period_year    = models.PositiveSmallIntegerField()
    period_month   = models.PositiveSmallIntegerField()
    total_hours    = models.DecimalField(max_digits=6, decimal_places=2)
    # Tarifs figés au moment de la clôture — un changement de tarif en
    # cours de mois suivant ne doit jamais modifier une paie déjà émise.
    hourly_rate_teacher = models.PositiveIntegerField()
    hourly_rate_billed  = models.PositiveIntegerField()
    gross_amount   = models.PositiveIntegerField(help_text="Montant versé à l'enseignant (FCFA)")
    billed_amount  = models.PositiveIntegerField(help_text="Montant facturé à l'établissement (FCFA)")
    xporadia_margin = models.PositiveIntegerField(help_text="billed_amount - gross_amount")
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Ligne de paie"
        verbose_name_plural = "Lignes de paie"
        ordering            = ["-period_year", "-period_month"]
        unique_together     = ("recruitment", "period_year", "period_month")

    def __str__(self):
        return f"Paie {self.period_month}/{self.period_year} — {self.recruitment.teacher.get_full_name()}"


class WalletTransaction(models.Model):
    """Historique du portefeuille enseignant — chaque clôture mensuelle y
    dépose une entrée traçable. Pas de solde stocké séparément : le solde
    est toujours la somme de cette table, pour ne jamais désynchroniser
    l'affichage de la réalité comptable."""

    teacher       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet_transactions"
    )
    payroll_entry = models.OneToOneField(PayrollEntry, on_delete=models.CASCADE, related_name="wallet_transaction")
    amount        = models.PositiveIntegerField()
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Transaction du portefeuille"
        verbose_name_plural = "Transactions du portefeuille"
        ordering            = ["-created_at"]

    def __str__(self):
        return f"{self.teacher.get_full_name()} : +{self.amount} FCFA"


class EstablishmentInvoiceStatus(models.TextChoices):
    UNPAID = "unpaid", "Non payée"
    PAID   = "paid",   "Payée"


class EstablishmentInvoice(models.Model):
    """Facture mensuelle d'un établissement — le pendant employeur de
    PayrollEntry (le montant que l'ENSEIGNANT reçoit) : c'est ce que
    l'ÉTABLISSEMENT doit à Xporadia pour les heures de ses enseignants
    (CDD/Vacation/Intérim) ce mois-là. Générée automatiquement à la
    clôture de paie (run_monthly_payroll), réglée ensuite par le
    directeur via Mobile Money ou carte bancaire (voir apps.payments)."""

    establishment = models.ForeignKey(
        "users.DirectorProfile", on_delete=models.CASCADE, related_name="invoices"
    )
    period_year   = models.PositiveSmallIntegerField()
    period_month  = models.PositiveSmallIntegerField()
    total_amount  = models.PositiveIntegerField(help_text="Somme des PayrollEntry.billed_amount du mois (FCFA)")
    status        = models.CharField(max_length=10, choices=EstablishmentInvoiceStatus.choices,
                                      default=EstablishmentInvoiceStatus.UNPAID)
    payment       = models.OneToOneField(
        "payments.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="establishment_invoice"
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    paid_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = "Facture établissement"
        verbose_name_plural = "Factures établissement"
        unique_together      = ("establishment", "period_year", "period_month")
        ordering            = ["-period_year", "-period_month"]

    def __str__(self):
        return f"Facture {self.period_month}/{self.period_year} — {self.establishment.school_name} ({self.status})"
