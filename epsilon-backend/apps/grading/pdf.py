"""Xporadia — apps/grading/pdf.py — même principe que apps.certification.pdf
et apps.internships.pdf : HTML → PDF via WeasyPrint."""
from decimal import ROUND_HALF_UP, Decimal

from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.academics.models import Enrollment, EnrollmentStatus, SubjectCategory
from apps.users.models import ChildSex

from .models import EvaluationType, ReportCardDistinction, ReportCardSanction, SubjectReportEntry, Term

TWO_PLACES = Decimal("0.01")

# Ordre d'affichage des groupes ("Bilan LETTRES" avant "Bilan SCIENCES"
# avant "Bilan AUTRES") — jamais l'ordre alphabétique des clés internes.
CATEGORY_ORDER = [SubjectCategory.LETTERS, SubjectCategory.SCIENCES, SubjectCategory.OTHER]
CATEGORY_LABELS = {
    SubjectCategory.LETTERS: "LETTRES",
    SubjectCategory.SCIENCES: "SCIENCES",
    SubjectCategory.OTHER: "AUTRES",
}

SEX_LABELS = {ChildSex.MALE: "Masculin", ChildSex.FEMALE: "Féminin"}


def _rank_descending(scored: list[tuple[int, Decimal]]) -> dict[int, int]:
    """{identifiant: rang} — rang 1 pour la moyenne la plus haute, même
    principe que services.compute_class_rankings mais générique (utilisé
    ici pour classer par matière et par groupe plutôt que sur la moyenne
    générale)."""
    ranked = sorted(scored, key=lambda t: t[1], reverse=True)
    return {identifier: index for index, (identifier, _avg) in enumerate(ranked, start=1)}


def ordinal(rank: int | None) -> str:
    """"1er" pour le premier rang, "Xème" au-delà — jamais "1ème" (faute
    en français). None si le rang n'existe pas (matière/groupe pas encore
    noté)."""
    if rank is None:
        return "—"
    return "1er" if rank == 1 else f"{rank}ème"


def render_report_card_pdf(report_card) -> bytes:
    from weasyprint import HTML

    school_class = report_card.school_class
    term = report_card.term
    child = report_card.child
    establishment = school_class.track.department.establishment

    enrollment = Enrollment.objects.filter(child=child, school_class=school_class).first()

    own_entries = list(report_card.subject_entries.all().order_by("subject_name"))

    # Rang par matière ET par groupe (bilan) — recalculés à partir des
    # SubjectReportEntry déjà figées de TOUTE la classe pour ce trimestre
    # (jamais une nouvelle moyenne : uniquement un classement sur des
    # chiffres déjà gelés à la génération, voir SubjectReportEntry).
    sibling_entries = list(
        SubjectReportEntry.objects.filter(
            report_card__school_class=school_class, report_card__term=term
        ).select_related("report_card")
    )

    scores_by_subject: dict[str, list[tuple[int, Decimal]]] = {}
    category_totals_by_child: dict[tuple[int, str], list] = {}
    for sibling in sibling_entries:
        if sibling.subject_average is None:
            continue
        scores_by_subject.setdefault(sibling.subject_name, []).append(
            (sibling.report_card.child_id, sibling.subject_average)
        )
        key = (sibling.report_card.child_id, sibling.category)
        totals = category_totals_by_child.setdefault(key, [Decimal("0"), Decimal("0")])
        totals[0] += sibling.subject_average * sibling.coefficient
        totals[1] += Decimal(sibling.coefficient)

    subject_rank_by_name = {name: _rank_descending(scores) for name, scores in scores_by_subject.items()}

    category_average_by_child: dict[tuple[int, str], Decimal] = {}
    for (child_id, category), (weighted, coeff) in category_totals_by_child.items():
        if coeff:
            category_average_by_child[(child_id, category)] = (weighted / coeff).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
    scores_by_category: dict[str, list[tuple[int, Decimal]]] = {}
    for (child_id, category), avg in category_average_by_child.items():
        scores_by_category.setdefault(category, []).append((child_id, avg))
    category_rank_by_key = {
        category: _rank_descending(scores) for category, scores in scores_by_category.items()
    }

    # Regroupement des matières DE CE bulletin par catégorie, avec la ligne
    # de sous-total ("Bilan ...") à la fin de chaque groupe.
    entries_by_category: dict[str, list] = {}
    for entry in own_entries:
        entries_by_category.setdefault(entry.category, []).append(entry)

    category_groups = []
    coefficient_grand_total = Decimal("0")
    m_coeff_grand_total = Decimal("0")
    for category in CATEGORY_ORDER:
        entries = entries_by_category.get(category)
        if not entries:
            continue
        rows = []
        for entry in entries:
            m_coeff = (
                (entry.subject_average * entry.coefficient).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                if entry.subject_average is not None
                else None
            )
            rank = subject_rank_by_name.get(entry.subject_name, {}).get(child.id)
            rows.append(
                {
                    "subject_name": entry.subject_name,
                    "coefficient": entry.coefficient,
                    "average": entry.subject_average,
                    "m_coeff": m_coeff,
                    "rank_label": ordinal(rank),
                    "teacher_name": entry.teacher_name,
                    "appreciation": entry.teacher_comment,
                }
            )
            coefficient_grand_total += entry.coefficient
            if m_coeff is not None:
                m_coeff_grand_total += m_coeff

        graded_entries = [e for e in entries if e.subject_average is not None]
        coeff_sum = sum((Decimal(e.coefficient) for e in entries), Decimal("0"))
        # Coeff sum de tout le groupe (toujours affiché, une matière compte
        # même sans note), mais Moy/M.Coeff n'ont de sens que sur les
        # matières déjà notées — jamais "0,00" quand rien n'est encore
        # calculable (voir "Philosophie" côté vitrine : notée seulement à
        # partir du T3, sans que ça n'affiche une moyenne fictive nulle
        # sur son groupe pour T1/T2).
        graded_coeff_sum = sum((Decimal(e.coefficient) for e in graded_entries), Decimal("0"))
        m_coeff_sum = sum((e.subject_average * e.coefficient for e in graded_entries), Decimal("0"))
        bilan_average = (
            (m_coeff_sum / graded_coeff_sum).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            if graded_coeff_sum
            else None
        )
        bilan_rank = category_rank_by_key.get(category, {}).get(child.id)
        category_groups.append(
            {
                "label": CATEGORY_LABELS[category],
                "rows": rows,
                "bilan": {
                    "coefficient": coeff_sum,
                    "m_coeff": m_coeff_sum.quantize(TWO_PLACES, rounding=ROUND_HALF_UP) if graded_entries else None,
                    "average": bilan_average,
                    "rank_label": ordinal(bilan_rank),
                },
            }
        )

    # Rappel — moyenne et rang du trimestre précédent DE LA MÊME ANNÉE
    # SCOLAIRE, jamais recalculés : ReportCard est déjà figé, une simple
    # lecture suffit.
    previous_report_card = None
    if term.number > 1:
        previous_term = Term.objects.filter(
            establishment=establishment, school_year=term.school_year, number=term.number - 1,
        ).first()
        if previous_term:
            from .models import ReportCard

            previous_report_card = ReportCard.objects.filter(child=child, term=previous_term).first()

    context = {
        "establishment_name": establishment.school_name,
        "establishment_address": establishment.address,
        "establishment_phone": establishment.phone,
        "establishment_email": establishment.contact_email,
        "establishment_code": establishment.establishment_code,
        "establishment_status_label": "Public" if establishment.is_public else "Privé",
        "term_label": str(term),
        "school_year": term.school_year,
        "student_name": f"{child.last_name} {child.first_name}".strip().upper(),
        "matricule": child.matricule,
        "sex_label": SEX_LABELS.get(child.sex, ""),
        "nationality": child.nationality,
        "birth_date": child.birth_date.strftime("%d/%m/%Y") if child.birth_date else "",
        "birth_place": child.birth_place,
        "class_name": str(school_class),
        "class_size": report_card.class_size,
        "is_repeating": enrollment.status == EnrollmentStatus.REPEATING if enrollment else False,
        "regime_label": (
            "Interne" if enrollment and enrollment.is_boarder is True
            else "Externe" if enrollment and enrollment.is_boarder is False
            else ""
        ),
        "is_assigned_label": "Oui" if (enrollment and enrollment.is_ministry_assigned) else "Non",
        "category_groups": category_groups,
        "coefficient_grand_total": coefficient_grand_total,
        "m_coeff_grand_total": m_coeff_grand_total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        "general_average": report_card.general_average,
        "rank_label": ordinal(report_card.rank),
        "class_average": report_card.class_average,
        "highest_average": report_card.highest_average,
        "lowest_average": report_card.lowest_average,
        "justified_absence_hours": report_card.justified_absence_hours,
        "unjustified_absence_hours": report_card.unjustified_absence_hours,
        "check_honor_roll": report_card.distinction == ReportCardDistinction.HONOR_ROLL,
        "check_honor_roll_encouragement": report_card.distinction == ReportCardDistinction.HONOR_ROLL_ENCOURAGEMENT,
        "check_honor_roll_congratulations": report_card.distinction == ReportCardDistinction.HONOR_ROLL_CONGRATULATIONS,
        "check_refused": report_card.distinction == ReportCardDistinction.REFUSED,
        "check_work_warning": report_card.sanction == ReportCardSanction.WORK_WARNING,
        "check_work_reprimand": report_card.sanction == ReportCardSanction.WORK_REPRIMAND,
        "check_conduct_warning": report_card.sanction == ReportCardSanction.CONDUCT_WARNING,
        "check_conduct_reprimand": report_card.sanction == ReportCardSanction.CONDUCT_REPRIMAND,
        "previous_report_card": previous_report_card,
        "previous_rank_label": ordinal(previous_report_card.rank) if previous_report_card else "",
        "homeroom_comment": report_card.homeroom_comment,
        "published_at": report_card.published_at.strftime("%d/%m/%Y"),
    }
    html_string = render_to_string("grading/report_card_pdf.html", context)
    return HTML(string=html_string).write_pdf()


def generate_and_attach_report_card(report_card) -> None:
    pdf_bytes = render_report_card_pdf(report_card)
    filename = f"bulletin_{report_card.child_id}_{report_card.term_id}.pdf"
    report_card.document.save(filename, ContentFile(pdf_bytes), save=False)
    report_card.save(update_fields=["document"])


def render_my_grades_pdf(child, subjects_data: list[dict]) -> bytes:
    """Export imprimable des notes chiffrées de l'élève (voir
    apps.grading.services.my_grades_for_child pour la structure de
    subjects_data) — jamais persisté sur disque, régénéré à la demande
    (voir MyGradesPdfView)."""
    from weasyprint import HTML

    enrollment = (
        Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
        .select_related("school_class__track__department__establishment")
        .first()
    )
    school_class = enrollment.school_class if enrollment else None
    establishment_name = (
        school_class.track.department.establishment.school_name if school_class else ""
    )

    subjects = []
    for subject in subjects_data:
        terms = []
        for term in subject["terms"]:
            evaluations = [
                {**ev, "eval_type_label": EvaluationType(ev["eval_type"]).label}
                for ev in term["evaluations"]
            ]
            terms.append({**term, "evaluations": evaluations})
        subjects.append({**subject, "terms": terms})

    context = {
        "establishment_name": establishment_name,
        "student_name": f"{child.first_name} {child.last_name}",
        "class_name": str(school_class) if school_class else "",
        "subjects": subjects,
        "generated_at": timezone.now().strftime("%d/%m/%Y"),
    }
    html_string = render_to_string("grading/my_grades_pdf.html", context)
    return HTML(string=html_string).write_pdf()
