from django.db import models


class IncidentSeverity(models.TextChoices):
    MINOR = "minor", "Mineur"
    MODERATE = "moderate", "Modéré"
    SERIOUS = "serious", "Grave"


class IncidentSanction(models.TextChoices):
    NONE = "none", "Aucune"
    WARNING = "warning", "Avertissement"
    REPRIMAND = "reprimand", "Blâme"
    DETENTION = "detention", "Retenue"
    SUSPENSION = "suspension", "Exclusion temporaire"


class DisciplinaryIncident(models.Model):
    """Incident disciplinaire pour un élève — la classe est figée au
    moment des faits (`school_class`), jamais recalculée depuis
    l'inscription courante : un élève qui change de classe en cours
    d'année garde un historique fidèle à la situation réelle de
    chaque incident."""

    establishment = models.ForeignKey(
        "users.DirectorProfile", on_delete=models.CASCADE, related_name="disciplinary_incidents"
    )
    child = models.ForeignKey("users.Child", on_delete=models.CASCADE, related_name="disciplinary_incidents")
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.CASCADE, related_name="disciplinary_incidents"
    )
    occurred_on = models.DateField()
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=IncidentSeverity.choices)
    sanction = models.CharField(max_length=12, choices=IncidentSanction.choices, default=IncidentSanction.NONE)
    recorded_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="recorded_incidents"
    )
    parent_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]

    def __str__(self):
        return f"{self.child} — {self.get_severity_display()} ({self.occurred_on})"
