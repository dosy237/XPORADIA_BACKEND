from django.db import models


class AdministrativeDocumentType(models.TextChoices):
    ATTESTATION_SCOLARITE = "attestation_scolarite", "Attestation de scolarité"
    CERTIFICAT_SCOLARITE = "certificat_scolarite", "Certificat de scolarité"
    CERTIFICAT_RADIATION = "certificat_radiation", "Certificat de radiation"


DOCUMENT_TYPE_PREFIXES = {
    AdministrativeDocumentType.ATTESTATION_SCOLARITE: "ATT",
    AdministrativeDocumentType.CERTIFICAT_SCOLARITE: "CS",
    AdministrativeDocumentType.CERTIFICAT_RADIATION: "RAD",
}


class AdministrativeDocument(models.Model):
    """Document officiel émis par le directeur pour un élève de son
    établissement — jamais régénéré à l'identique après coup (voir
    pdf.py) : ce modèle ne fait que fixer le numéro de référence et la
    date d'émission, le contenu est reconstruit à la demande depuis les
    données courantes de l'élève au moment de l'émission (école,
    classe, statut)."""

    establishment = models.ForeignKey(
        "users.DirectorProfile", on_delete=models.CASCADE, related_name="administrative_documents"
    )
    child = models.ForeignKey(
        "users.Child", on_delete=models.CASCADE, related_name="administrative_documents"
    )
    document_type = models.CharField(max_length=30, choices=AdministrativeDocumentType.choices)
    school_year = models.CharField(max_length=9)
    reference_number = models.CharField(max_length=40, unique=True)
    issued_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="issued_administrative_documents"
    )
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"{self.reference_number} — {self.child}"
