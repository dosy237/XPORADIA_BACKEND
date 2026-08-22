"""Xporadia — apps/grading/pdf.py — même principe que apps.certification.pdf
et apps.internships.pdf : HTML → PDF via WeasyPrint."""
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.academics.models import Enrollment, EnrollmentStatus

from .models import EvaluationType


def render_report_card_pdf(report_card) -> bytes:
    from weasyprint import HTML

    context = {
        "establishment_name": report_card.school_class.track.department.establishment.school_name,
        "term_label": str(report_card.term),
        "school_year": report_card.term.school_year,
        "student_name": f"{report_card.child.first_name} {report_card.child.last_name}",
        "class_name": str(report_card.school_class),
        "subject_entries": report_card.subject_entries.all(),
        "general_average": report_card.general_average,
        "rank": report_card.rank,
        "class_size": report_card.class_size,
        "class_average": report_card.class_average,
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
