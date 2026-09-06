"""
Xporadia — apps/certification/pdf.py

Génération du certificat PDF, sur le même principe que le PDF de
convention de stage (apps.internships.pdf) : HTML → PDF via WeasyPrint,
avec un QR code intégré pointant vers la page de vérification publique.
"""
import base64
from io import BytesIO

from django.core.files.base import ContentFile
from django.template.loader import render_to_string

LEVEL_LABELS_FR = {"bronze": "Bronze", "silver": "Argent", "gold": "Or"}


def _qr_code_base64(data: str) -> str:
    import qrcode

    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def render_certificate_pdf(certification) -> bytes:
    from django.conf import settings
    from weasyprint import HTML

    verify_url = f"{settings.INVITE_LINK_BASE}/verify/{certification.qr_code}"
    context = {
        "teacher_name": certification.teacher.get_full_name(),
        "module_title": certification.module.title,
        "level_label": LEVEL_LABELS_FR.get(certification.level, certification.level),
        "score": certification.score_total,
        "points": certification.points_awarded,
        "issued_at": certification.issued_at.strftime("%d/%m/%Y"),
        "qr_code": certification.qr_code,
        "qr_image_base64": _qr_code_base64(verify_url),
    }
    html_string = render_to_string("certification/certificate_pdf.html", context)
    return HTML(string=html_string).write_pdf()


def generate_and_attach_certificate(certification) -> None:
    pdf_bytes = render_certificate_pdf(certification)
    filename = f"certificat_{certification.qr_code}.pdf"
    certification.document.save(filename, ContentFile(pdf_bytes), save=False)
    certification.save(update_fields=["document"])
