"""
Xporadia — apps/certification/constants.py

Seuils de points définissant le badge visible d'un enseignant. Le badge
n'est plus "le meilleur certificat obtenu" mais un cumul : chaque
formation validée apporte des points fixes (voir TrainingModule.points),
et c'est le total qui détermine le niveau affiché sur le profil et
l'annuaire. Ajuster ici ne nécessite aucune migration ni changement de
logique ailleurs dans le code.
"""
from apps.certification.models import CertificationLevel

# {niveau: points minimum requis pour l'atteindre} — Zéro est le palier de
# départ (aucune certification encore validée), pas une absence de niveau :
# un enseignant a toujours un badge affichable, même à 0 point. Bronze à 1
# point préserve le comportement historique (la toute première certification
# validée fait déjà sortir de Zéro) ; Silver/Gold inchangés, Platine et
# Diamant ajoutés au-dessus.
POINTS_THRESHOLDS = {
    CertificationLevel.ZERO: 0,
    CertificationLevel.BRONZE: 1,
    CertificationLevel.SILVER: 25,
    CertificationLevel.GOLD: 75,
    CertificationLevel.PLATINUM: 200,
    CertificationLevel.DIAMOND: 400,
}


def badge_for_points(total_points: int) -> str:
    """Renvoie le badge le plus élevé atteint avec ce total de points —
    toujours au moins Zéro, jamais None."""
    badge = CertificationLevel.ZERO
    for level, threshold in sorted(POINTS_THRESHOLDS.items(), key=lambda kv: kv[1]):
        if total_points >= threshold:
            badge = level
    return badge


LEVEL_ORDER = [
    CertificationLevel.ZERO,
    CertificationLevel.BRONZE,
    CertificationLevel.SILVER,
    CertificationLevel.GOLD,
    CertificationLevel.PLATINUM,
    CertificationLevel.DIAMOND,
]


def is_gold_or_above(level: str) -> bool:
    """Or, Platine ou Diamant — jamais une égalité stricte avec "gold" seul,
    qui exclurait à tort les paliers au-dessus (bug réel corrigé dans la
    bibliothèque : un enseignant Platine se voyait refuser la contribution
    réservée aux enseignants "certifiés Or")."""
    return LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(CertificationLevel.GOLD)


def points_to_next_level(total_points: int) -> dict | None:
    """Combien de points manquent pour le prochain palier — alimente la
    frise de progression sur le profil. None si déjà au niveau maximum."""
    for level, threshold in sorted(POINTS_THRESHOLDS.items(), key=lambda kv: kv[1]):
        if total_points < threshold:
            return {"next_level": level, "points_needed": threshold - total_points, "threshold": threshold}
    return None


# --- Rattrapage (CDC US-02-08) — une session ratée, pas une compétence à
# repayer : le rattrapage concerne un ÉCHEC, jamais une certification déjà
# obtenue. Une fois payée et validée, une certification ne s'expire jamais
# et ne se repaie jamais — voir Certification.is_valid, qui n'est basculé
# que par une action de modération explicite (fraude), jamais par le temps.
RETAKE_MIN_SCORE = 50
# Délai minimum avant de pouvoir passer le rattrapage.
RETAKE_MIN_WAIT_DAYS = 7
# Fenêtre pendant laquelle le rattrapage reste ouvert après l'échec.
RETAKE_WINDOW_DAYS = 30
# Le rattrapage coûte la moitié du tarif du module.
RETAKE_FEE_RATIO = 0.5


# --- Repère salarial (CDC Partie II — fourchettes recommandées par niveau)
# Sert uniquement d'outil de négociation PRIVÉ pour l'enseignant lui-même —
# jamais affiché publiquement, jamais utilisé pour brider ce qu'un
# établissement peut réellement proposer.
SALARY_RANGES_FCFA_PER_MONTH = {
    CertificationLevel.ZERO: (60_000, 90_000),
    CertificationLevel.BRONZE: (80_000, 120_000),
    CertificationLevel.SILVER: (120_000, 200_000),
    CertificationLevel.GOLD: (200_000, 350_000),
    CertificationLevel.PLATINUM: (350_000, 500_000),
    CertificationLevel.DIAMOND: (500_000, 750_000),
}
