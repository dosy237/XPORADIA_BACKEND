from django.db import transaction

from .models import DOCUMENT_TYPE_PREFIXES, AdministrativeDocument


def _next_reference_number(establishment, document_type: str, school_year: str) -> str:
    """Numéro séquentiel par établissement/type/année scolaire, ex.
    "ATT-2025-2026-000001" — jamais réutilisé même si un document est
    supprimé, puisqu'il compte les documents déjà émis plutôt que de
    tenir un compteur séparé."""
    prefix = DOCUMENT_TYPE_PREFIXES[document_type]
    count = AdministrativeDocument.objects.filter(
        establishment=establishment, document_type=document_type, school_year=school_year
    ).count()
    return f"{prefix}-{school_year}-{count + 1:06d}"


def issue_administrative_document(establishment, child, document_type: str, school_year: str, issued_by):
    with transaction.atomic():
        reference_number = _next_reference_number(establishment, document_type, school_year)
        return AdministrativeDocument.objects.create(
            establishment=establishment,
            child=child,
            document_type=document_type,
            school_year=school_year,
            reference_number=reference_number,
            issued_by=issued_by,
        )


def enrollment_for_document(document):
    """Inscription de référence pour le contenu du document : la plus
    récente à cet établissement pour cette année scolaire, quel que
    soit son statut — une attestation de scolarité veut l'inscription
    active, un certificat de radiation veut la dernière avant le
    départ, et les deux se trouvent de la même façon (la plus récente
    correspondant à l'année scolaire visée)."""
    from apps.academics.models import Enrollment

    return (
        Enrollment.objects.filter(
            child=document.child,
            school_class__track__department__establishment=document.establishment,
            school_class__school_year=document.school_year,
        )
        .select_related("school_class__track__department")
        .order_by("-enrolled_at")
        .first()
    )
