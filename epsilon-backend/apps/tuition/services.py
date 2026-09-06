"""
Xporadia — apps/tuition/services.py

Le statut d'une tranche pour un élève et les totaux d'un établissement se
déduisent toujours des FeePayment réellement enregistrés — jamais un champ
stocké séparément qui pourrait diverger (voir models.py, docstring de
module).
"""
from django.db.models import Sum

from .models import FeeInstallment, FeePayment, FeeSchedule


def installment_status(installment: FeeInstallment, child) -> dict:
    paid = FeePayment.objects.filter(fee_installment=installment, child=child).aggregate(
        total=Sum("amount_paid")
    )["total"] or 0
    if paid >= installment.amount:
        status = "paid"
    elif paid > 0:
        status = "partial"
    else:
        from django.utils import timezone

        status = "late" if installment.due_date < timezone.localdate() else "pending"
    return {"amount_paid": paid, "amount_due": installment.amount - paid, "status": status}


def active_fee_schedule_for_child(child):
    """L'échéancier applicable à un élève se déduit de son établissement
    et de son année scolaire d'inscription active — pas de table
    d'association séparée (voir spécification)."""
    from apps.academics.models import Enrollment, EnrollmentStatus

    enrollment = (
        Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
        .select_related("school_class__track__department__establishment")
        .first()
    )
    if not enrollment:
        return None
    establishment = enrollment.school_class.track.department.establishment
    return FeeSchedule.objects.filter(
        establishment=establishment, school_year=enrollment.school_class.school_year
    ).first()


def establishment_fee_totals(establishment, school_year: str) -> dict:
    schedule = FeeSchedule.objects.filter(establishment=establishment, school_year=school_year).first()
    if not schedule:
        return {"total_expected": 0, "total_collected": 0}
    total_expected = schedule.installments.aggregate(total=Sum("amount"))["total"] or 0
    total_collected = FeePayment.objects.filter(fee_installment__fee_schedule=schedule).aggregate(
        total=Sum("amount_paid")
    )["total"] or 0
    return {"total_expected": total_expected, "total_collected": total_collected}


def late_children_for_schedule(schedule: FeeSchedule):
    """Enfants inscrits dans l'établissement de cet échéancier, pour son
    année scolaire, avec au moins une tranche en retard (échue, non
    intégralement payée)."""
    from apps.academics.models import Enrollment, EnrollmentStatus

    children = [
        e.child
        for e in Enrollment.objects.filter(
            school_class__track__department__establishment=schedule.establishment,
            school_class__school_year=schedule.school_year,
            status=EnrollmentStatus.ACTIVE,
        ).select_related("child")
    ]
    late = []
    for child in children:
        entries = [
            {"installment": installment, **installment_status(installment, child)}
            for installment in schedule.installments.all()
        ]
        if any(e["status"] == "late" for e in entries):
            late.append({"child": child, "installments": entries})
    return late
