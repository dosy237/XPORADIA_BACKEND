"""Xporadia — apps/documents/pdf.py — même principe que apps.grading.pdf :
HTML -> PDF via WeasyPrint."""
from django.template.loader import render_to_string

from apps.users.models import ChildSex

from .models import AdministrativeDocumentType
from .services import enrollment_for_document


def _body_paragraphs(document, child, establishment, enrollment) -> list[str]:
    civility = "Le/La nommé(e)" if not child.sex else ("Le nommé" if child.sex == ChildSex.MALE else "La nommée")
    born = ""
    if child.birth_date:
        born = f", né(e) le {child.birth_date.strftime('%d/%m/%Y')}"
        if child.birth_place:
            born += f" à {child.birth_place}"
    class_name = str(enrollment.school_class) if enrollment else "—"

    if document.document_type == AdministrativeDocumentType.CERTIFICAT_RADIATION:
        left_on = enrollment.ended_at.strftime("%d/%m/%Y") if enrollment and enrollment.ended_at else "—"
        return [
            f"Je soussigné(e), Directeur/Directrice de {establishment.school_name}, certifie que "
            f"l'élève {child.first_name} {child.last_name}{born}, immatriculé(e) sous le numéro "
            f"{child.matricule or '—'}, a été inscrit(e) en classe de {class_name} au titre de "
            f"l'année scolaire {document.school_year}.",
            f"Le/La susnommé(e) a quitté l'établissement le {left_on} et n'y est plus inscrit(e) "
            f"depuis cette date.",
            "En foi de quoi, la présente attestation lui est délivrée pour servir et valoir ce que "
            "de droit.",
        ]

    verb = "atteste" if document.document_type == AdministrativeDocumentType.ATTESTATION_SCOLARITE else "certifie"
    return [
        f"Je soussigné(e), Directeur/Directrice de {establishment.school_name}, {verb} que "
        f"{civility.lower()} {child.first_name} {child.last_name}{born}, immatriculé(e) sous le "
        f"numéro {child.matricule or '—'}, est régulièrement inscrit(e) en classe de {class_name} "
        f"au titre de l'année scolaire {document.school_year}.",
        "En foi de quoi, la présente attestation lui est délivrée pour servir et valoir ce que de "
        "droit.",
    ]


DOCUMENT_TITLES = {
    AdministrativeDocumentType.ATTESTATION_SCOLARITE: "Attestation de scolarité",
    AdministrativeDocumentType.CERTIFICAT_SCOLARITE: "Certificat de scolarité",
    AdministrativeDocumentType.CERTIFICAT_RADIATION: "Certificat de radiation",
}


def render_administrative_document_pdf(document) -> bytes:
    from weasyprint import HTML

    from apps.grading.pdf import _image_data_uri

    child = document.child
    establishment = document.establishment
    enrollment = enrollment_for_document(document)

    context = {
        "document_title": DOCUMENT_TITLES[document.document_type],
        "reference_number": document.reference_number,
        "establishment_name": establishment.school_name,
        "establishment_address": establishment.address,
        "establishment_phone": establishment.phone,
        "establishment_email": establishment.contact_email,
        "establishment_code": establishment.establishment_code,
        "establishment_status_label": "Public" if establishment.is_public else "Privé",
        "establishment_logo_uri": _image_data_uri(establishment.logo),
        "school_year": document.school_year,
        "issued_at": document.issued_at.strftime("%d/%m/%Y"),
        "issued_by_name": document.issued_by.get_full_name() if document.issued_by else "",
        "paragraphs": _body_paragraphs(document, child, establishment, enrollment),
    }
    html_string = render_to_string("documents/administrative_document_pdf.html", context)
    return HTML(string=html_string).write_pdf()
