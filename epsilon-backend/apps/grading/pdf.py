"""Xporadia — apps/grading/pdf.py — même principe que apps.certification.pdf
et apps.internships.pdf : HTML → PDF via WeasyPrint."""
from django.core.files.base import ContentFile
from django.template.loader import render_to_string


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
