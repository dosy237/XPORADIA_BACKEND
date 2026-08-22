"""
Xporadia — apps/grading/services.py

Calcul des moyennes — en Decimal partout (jamais float) pour ne jamais
introduire d'erreur d'arrondi dans un système où l'équité compte. Les
moyennes sont recalculées à la volée tant qu'un bulletin n'est pas
publié ; ReportCard fige le résultat définitivement à la publication.
"""
from decimal import ROUND_HALF_UP, Decimal

from apps.academics.models import Enrollment, EnrollmentStatus, Subject

from .models import Evaluation, Grade, Term

TWO_PLACES = Decimal("0.01")


def compute_subject_average(child, subject: Subject, term) -> Decimal | None:
    """Moyenne pondérée des notes de CETTE matière pour CE trimestre —
    pondérée par le coefficient de chaque évaluation (une composition
    pèse plus qu'une interrogation). Chaque note est d'abord ramenée sur
    20 selon le barème propre de son évaluation (max_score) AVANT
    pondération : sans cette normalisation, une note sur 10 pèserait deux
    fois moins qu'une note sur 20 de même coefficient, ce qui fausserait
    la moyenne dès qu'une matière mélange des échelles différentes.
    Ignore les notes dispensées et les évaluations sans note saisie pour
    cet élève (jamais comptées comme zéro). None si rien à calculer
    (pas encore de note saisie)."""
    grades = (
        Grade.objects.filter(
            evaluation__subject=subject, evaluation__term=term, child=child,
            is_excused=False, score__isnull=False,
        )
        .select_related("evaluation")
    )
    total_weighted = Decimal("0")
    total_coefficient = Decimal("0")
    for grade in grades:
        max_score = grade.evaluation.max_score
        if not max_score:
            continue  # barème invalide — garde-fou, ne devrait pas arriver (MinValueValidator(1))
        normalized_on_20 = (grade.score / Decimal(max_score)) * Decimal("20")
        coeff = Decimal(grade.evaluation.coefficient)
        total_weighted += normalized_on_20 * coeff
        total_coefficient += coeff
    if total_coefficient == 0:
        return None
    return (total_weighted / total_coefficient).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def active_enrollments(school_class):
    """Effectif actif d'une classe à l'instant de l'appel — jamais une
    photo figée en début de trimestre : un élève inscrit en cours de
    route apparaît automatiquement dans toute vue qui réutilise cette
    fonction (grille de notes, saisie en lot par évaluation...) sans
    action manuelle de l'enseignant."""
    return (
        Enrollment.objects.filter(school_class=school_class, status=EnrollmentStatus.ACTIVE)
        .select_related("child__user")
        .order_by("child__first_name")
    )


def compute_general_average(child, school_class, term) -> Decimal | None:
    """Moyenne générale — pondérée par le coefficient de chaque matière
    (Subject.coefficient, fixé par le directeur). Une matière sans
    aucune note saisie pour cet élève est simplement absente du calcul
    (n'est pas comptée comme 0)."""
    subjects = Subject.objects.filter(school_class=school_class)
    total_weighted = Decimal("0")
    total_coefficient = Decimal("0")
    for subject in subjects:
        subject_avg = compute_subject_average(child, subject, term)
        if subject_avg is None:
            continue
        coeff = Decimal(subject.coefficient)
        total_weighted += subject_avg * coeff
        total_coefficient += coeff
    if total_coefficient == 0:
        return None
    return (total_weighted / total_coefficient).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_class_rankings(school_class, term) -> list[dict]:
    """Classement de la classe pour ce trimestre — trié par moyenne
    générale décroissante. Les élèves sans moyenne calculable (aucune
    note saisie nulle part) sont exclus du classement mais listés à part,
    pour que le directeur voie tout de suite qui n'a encore aucune note."""
    enrollments = Enrollment.objects.filter(
        school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).select_related("child__user")

    ranked = []
    without_average = []
    for enrollment in enrollments:
        avg = compute_general_average(enrollment.child, school_class, term)
        if avg is None:
            without_average.append(enrollment.child)
        else:
            ranked.append({"child": enrollment.child, "general_average": avg})

    ranked.sort(key=lambda entry: entry["general_average"], reverse=True)
    for index, entry in enumerate(ranked, start=1):
        entry["rank"] = index
    entry_count = len(ranked)
    for entry in ranked:
        entry["class_size"] = entry_count

    class_average = (
        (sum(e["general_average"] for e in ranked) / entry_count).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if entry_count
        else None
    )
    # `ranked` est déjà trié décroissant — le premier/dernier élément porte
    # directement la plus forte/plus faible moyenne, sans nouveau calcul.
    highest_average = ranked[0]["general_average"] if ranked else None
    lowest_average = ranked[-1]["general_average"] if ranked else None
    return {
        "ranked": ranked,
        "without_average": without_average,
        "class_average": class_average,
        "highest_average": highest_average,
        "lowest_average": lowest_average,
    }


def suggest_distinction(general_average: Decimal | None) -> str:
    """Suggestion automatique de mention à partir de la moyenne générale —
    convention courante (Tableau d'honneur à partir de 12/20, +
    Encouragements à partir de 14, + Félicitations à partir de 16). Reste
    une SUGGESTION que le titulaire peut corriger avant publication (voir
    GenerateReportCardsView) : jamais "Refusé(e)", qui reste une décision
    humaine du conseil de classe, jamais déduite d'un seuil."""
    from .models import ReportCardDistinction

    if general_average is None:
        return ReportCardDistinction.NONE
    if general_average >= Decimal("16"):
        return ReportCardDistinction.HONOR_ROLL_CONGRATULATIONS
    if general_average >= Decimal("14"):
        return ReportCardDistinction.HONOR_ROLL_ENCOURAGEMENT
    if general_average >= Decimal("12"):
        return ReportCardDistinction.HONOR_ROLL
    return ReportCardDistinction.NONE


def my_grades_for_child(child) -> list[dict]:
    """Notes chiffrées de CET élève, groupées par matière puis par
    trimestre (le plus récent d'abord), moyenne de matière déjà calculée
    pour chaque trimestre — extrait de MyGradesView pour être réutilisé
    tel quel par la vue PDF (même données, deux présentations)."""
    enrollment = (
        Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
        .select_related("school_class")
        .first()
    )
    if not enrollment:
        return []

    subjects = Subject.objects.filter(school_class=enrollment.school_class).order_by("name")
    grades = (
        Grade.objects.filter(child=child, evaluation__subject__in=subjects, score__isnull=False)
        .select_related("evaluation", "evaluation__term", "evaluation__subject")
        .order_by("-evaluation__date")
    )

    grades_by_subject_term = {}
    for grade in grades:
        key = (grade.evaluation.subject_id, grade.evaluation.term_id)
        grades_by_subject_term.setdefault(key, []).append(grade)

    result = []
    for subject in subjects:
        terms_seen = {
            term_id for (subject_id, term_id) in grades_by_subject_term if subject_id == subject.id
        }
        if not terms_seen:
            continue
        term_entries = []
        for term in Term.objects.filter(id__in=terms_seen).order_by("-school_year", "-number"):
            subject_grades = grades_by_subject_term[(subject.id, term.id)]
            term_entries.append(
                {
                    "term_id": term.id,
                    "term_label": str(term),
                    "subject_average": compute_subject_average(child, subject, term),
                    "evaluations": [
                        {
                            "id": g.evaluation.id,
                            "title": g.evaluation.title,
                            "eval_type": g.evaluation.eval_type,
                            "score": g.score,
                            "max_score": g.evaluation.max_score,
                            "coefficient": g.evaluation.coefficient,
                            "date": g.evaluation.date,
                        }
                        for g in subject_grades
                    ],
                }
            )
        result.append(
            {
                "subject_id": subject.id,
                "subject_name": subject.name,
                "coefficient": subject.coefficient,
                "terms": term_entries,
            }
        )
    return result
