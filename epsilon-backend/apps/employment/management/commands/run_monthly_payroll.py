"""
Xporadia — run_monthly_payroll

À exécuter une fois par mois (Celery Beat en production, le 1er du mois
suivant celui à clôturer). Pour chaque recrutement non-CDI ayant des
heures VALIDÉES non encore payées sur le mois écoulé :
  - crée une PayrollEntry (tarifs figés au moment de la clôture)
  - crédite le portefeuille de l'enseignant (WalletTransaction)
  - marque les WorkedHours concernées comme rattachées à cette paie
    (empêche tout double comptage sur une relance ultérieure)
  - notifie l'enseignant

Usage : `manage.py run_monthly_payroll` (clôture le mois précédent par
défaut) ou `manage.py run_monthly_payroll --year 2026 --month 7` pour un
mois précis (rattrapage).
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.employment.models import (
    EstablishmentInvoice,
    PayrollEntry,
    Recruitment,
    WalletTransaction,
    WorkedHours,
    WorkedHoursStatus,
)
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user


class Command(BaseCommand):
    help = "Clôture la paie mensuelle des enseignants en CDD/Vacation/Intérim."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None)
        parser.add_argument("--month", type=int, default=None)

    def handle(self, *args, **options):
        today = timezone.localdate()
        if options["year"] and options["month"]:
            year, month = options["year"], options["month"]
        else:
            # Par défaut, clôture le mois précédent — cette commande est
            # censée tourner en tout début de mois suivant.
            first_of_this_month = today.replace(day=1)
            last_month_end = first_of_this_month - timezone.timedelta(days=1)
            year, month = last_month_end.year, last_month_end.month

        entries_created = 0
        recruitments = Recruitment.objects.exclude(contract_type="cdi").select_related(
            "teacher", "school__director_profile"
        )

        for recruitment in recruitments:
            approved_hours = WorkedHours.objects.filter(
                recruitment=recruitment,
                status=WorkedHoursStatus.APPROVED,
                payroll_entry__isnull=True,
                date__year=year,
                date__month=month,
            )
            total_hours = approved_hours.aggregate(total=Sum("hours"))["total"]
            if not total_hours:
                continue

            if not recruitment.hourly_rate_teacher or not recruitment.hourly_rate_billed:
                self.stdout.write(
                    self.style.WARNING(
                        f"Recrutement {recruitment.id} sans tarif horaire renseigné — ignoré."
                    )
                )
                continue

            gross_amount = round(total_hours * recruitment.hourly_rate_teacher)
            billed_amount = round(total_hours * recruitment.hourly_rate_billed)

            entry, created = PayrollEntry.objects.get_or_create(
                recruitment=recruitment, period_year=year, period_month=month,
                defaults=dict(
                    total_hours=total_hours,
                    hourly_rate_teacher=recruitment.hourly_rate_teacher,
                    hourly_rate_billed=recruitment.hourly_rate_billed,
                    gross_amount=gross_amount,
                    billed_amount=billed_amount,
                    xporadia_margin=billed_amount - gross_amount,
                ),
            )
            if not created:
                continue  # déjà clôturé pour ce mois — idempotent

            approved_hours.update(payroll_entry=entry)

            WalletTransaction.objects.create(teacher=recruitment.teacher, payroll_entry=entry, amount=gross_amount)

            notify_user(
                recruitment.teacher,
                NotificationType.PAYMENT_RECEIVED,
                title="Paie du mois disponible",
                body=(
                    f"{total_hours}h validées pour {month}/{year} — {gross_amount} FCFA "
                    "crédités sur votre portefeuille Xporadia."
                ),
                data={"payroll_entry_id": entry.id},
            )
            entries_created += 1

        # Une facture par établissement, agrégeant le montant facturé
        # (billed_amount) de toutes les lignes de paie du mois — jamais
        # de double comptage : PayrollEntry.get_or_create ci-dessus est
        # déjà idempotent, et EstablishmentInvoice l'est aussi via
        # get_or_create ci-dessous.
        invoices_created = 0
        billed_by_establishment = {}
        for entry in PayrollEntry.objects.filter(period_year=year, period_month=month).select_related(
            "recruitment__school__director_profile"
        ):
            establishment = entry.recruitment.school.director_profile
            billed_by_establishment.setdefault(establishment, 0)
            billed_by_establishment[establishment] += entry.billed_amount

        for establishment, total in billed_by_establishment.items():
            invoice, created = EstablishmentInvoice.objects.get_or_create(
                establishment=establishment, period_year=year, period_month=month,
                defaults={"total_amount": total},
            )
            if not created:
                continue
            notify_user(
                establishment.user,
                NotificationType.INVOICE_READY,
                title="Facture du mois disponible",
                body=f"Facture {month}/{year} : {total} FCFA pour les heures de vos enseignants.",
                data={"invoice_id": invoice.id},
            )
            invoices_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Clôture {month}/{year} : {entries_created} ligne(s) de paie, "
                f"{invoices_created} facture(s) établissement créée(s)."
            )
        )
