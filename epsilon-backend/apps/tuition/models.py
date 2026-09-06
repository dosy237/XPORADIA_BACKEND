"""
Xporadia — apps/tuition/models.py

Frais de scolarité — échéancier par établissement et année scolaire,
paiements enregistrés manuellement par le personnel (espèces, Mobile
Money, virement...), jamais une intégration de paiement en ligne (voir
apps.payments, un système de passerelle complètement différent réservé
aux paiements de la plateforme Xporadia elle-même).

Principe directeur : le statut d'une tranche pour un élève (payée /
partielle / en retard) se déduit toujours de la somme de ses FeePayment
par rapport au montant de la tranche — jamais un champ de statut stocké
séparément qui pourrait diverger de la réalité des paiements enregistrés
(voir services.installment_status).
"""
from django.conf import settings
from django.db import models

from apps.users.models import Child, DirectorProfile


class FeeSchedule(models.Model):
    """Échéancier de frais de scolarité d'un établissement pour une année
    scolaire donnée — un seul par établissement et par année."""

    establishment = models.ForeignKey(DirectorProfile, on_delete=models.CASCADE, related_name="fee_schedules")
    school_year = models.CharField(max_length=9, verbose_name="Année scolaire", help_text="Ex. 2025-2026")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Échéancier de frais de scolarité"
        verbose_name_plural = "Échéanciers de frais de scolarité"
        unique_together = ("establishment", "school_year")

    def __str__(self):
        return f"{self.establishment.school_name} — {self.school_year}"


class FeeInstallment(models.Model):
    """Une tranche de l'échéancier — ex. \"Inscription\", \"1er versement\"."""

    fee_schedule = models.ForeignKey(FeeSchedule, on_delete=models.CASCADE, related_name="installments")
    name = models.CharField(max_length=100)
    amount = models.PositiveIntegerField(help_text="FCFA")
    due_date = models.DateField()

    class Meta:
        verbose_name = "Tranche de frais de scolarité"
        verbose_name_plural = "Tranches de frais de scolarité"
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.name} — {self.amount} FCFA ({self.fee_schedule})"


class PaymentChannel(models.TextChoices):
    CASH = "cash", "Espèces"
    MOBILE_MONEY = "mobile_money", "Mobile Money"
    BANK_TRANSFER = "bank_transfer", "Virement"
    OTHER = "other", "Autre"


class FeePayment(models.Model):
    """Un versement réel enregistré sur une tranche, pour un élève — une
    tranche peut recevoir plusieurs FeePayment (paiement partiel en
    plusieurs fois), voir services.installment_status pour le statut
    déduit."""

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="fee_payments")
    fee_installment = models.ForeignKey(FeeInstallment, on_delete=models.CASCADE, related_name="payments")
    amount_paid = models.PositiveIntegerField(help_text="FCFA")
    payment_channel = models.CharField(max_length=15, choices=PaymentChannel.choices, default=PaymentChannel.CASH)
    paid_at = models.DateTimeField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        verbose_name = "Paiement de frais de scolarité"
        verbose_name_plural = "Paiements de frais de scolarité"
        ordering = ["-paid_at"]

    def __str__(self):
        return f"{self.child.first_name} — {self.amount_paid} FCFA sur {self.fee_installment.name}"
