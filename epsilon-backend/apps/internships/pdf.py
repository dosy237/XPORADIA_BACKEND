"""
Xporadia — apps/internships/pdf.py

Génération du PDF de convention de stage, aux couleurs de l'entreprise
d'accueil (branding choisi une fois sur CompanyProfile). HTML → PDF via
WeasyPrint plutôt qu'une librairie de dessin bas niveau (reportlab) : le
gabarit reste lisible et modifiable comme n'importe quel template Django,
sans coordonnées x/y à la main.
"""
from datetime import date
from io import BytesIO

from django.core.files.base import ContentFile
from django.template.loader import render_to_string


def render_convention_pdf(convention) -> bytes:
    from weasyprint import HTML

    application = convention.application
    offer = application.offer
    company_profile = offer.company.company_profile
    student = application.student

    context = {
        "company_name": company_profile.company_name,
        "company_address": company_profile.address,
        "primary_color": company_profile.brand_primary_color,
        "secondary_color": company_profile.brand_secondary_color,
        "position_title": convention.position_title or offer.title,
        "student_name": f"{student.first_name} {student.last_name}".strip(),
        "school_name": application.school.director_profile.school_name,
        "domain": offer.domain,
        "city": offer.city,
        "period_start": offer.period_start.strftime("%d/%m/%Y"),
        "period_end": offer.period_end.strftime("%d/%m/%Y"),
        "duration_weeks": offer.duration_weeks,
        "missions": offer.missions,
        "generated_date": date.today().strftime("%d/%m/%Y"),
    }
    html_string = render_to_string("internships/convention_pdf.html", context)
    return HTML(string=html_string).write_pdf()


def generate_and_attach_convention_pdf(convention) -> None:
    """Génère le PDF, l'enregistre sur la convention, et le dépose comme
    pièce jointe dans le canal de stage — créant ce dernier au besoin
    (une entreprise peut générer la convention avant la signature
    complète, donc avant que le canal n'existe forcément déjà)."""
    from apps.messaging.services import ensure_internship_channel
    from apps.messaging.models import Message

    pdf_bytes = render_convention_pdf(convention)
    filename = f"convention_{convention.id}.pdf"
    convention.document.save(filename, ContentFile(pdf_bytes), save=False)
    convention.save(update_fields=["document"])

    channel = ensure_internship_channel(convention)
    if channel:
        Message.objects.create(
            channel=channel,
            author=convention.application.offer.company,
            body="Voici la convention de stage générée.",
            attachments=[{"name": filename, "url": convention.document.url, "type": "application/pdf"}],
        )
