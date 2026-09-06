from .models import DisciplinaryIncident, IncidentSeverity


def establishment_incident_totals(establishment, school_year: str) -> dict:
    """Comptage par gravité pour une année scolaire — calculé à la
    volée à chaque appel, jamais mis en cache : le volume d'incidents
    d'un établissement reste faible, un recalcul systématique est sans
    coût perceptible et évite tout risque de compteur périmé."""
    incidents = DisciplinaryIncident.objects.filter(
        establishment=establishment, school_class__school_year=school_year
    )
    counts = {choice.value: 0 for choice in IncidentSeverity}
    for severity in incidents.values_list("severity", flat=True):
        counts[severity] += 1
    return {"total": incidents.count(), "by_severity": counts}
