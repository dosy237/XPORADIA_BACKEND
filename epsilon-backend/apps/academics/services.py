"""
Xporadia — apps/academics/services.py

Logique de scope temporel de l'emploi du temps et de l'agenda personnel.

Principe directeur : les vacances ne sont jamais saisies séparément — une
date est en vacances si elle ne tombe dans AUCUN Term de l'année scolaire
(petites vacances entre deux trimestres consécutifs, grandes vacances avant
le premier ou après le dernier). `term_for_date` est l'unique fonction qui
fait cette déduction ; toute autre logique qui a besoin de savoir "cette
date est-elle un jour d'école" doit passer par elle, jamais la dupliquer.

Limite acceptée : si un seul Term existe pour une année scolaire, le
système ne peut pas savoir où commence la prochaine vacance (aucune borne
suivante à comparer) — comportement naturel de la fonction, pas un bug à
corriger.
"""
from django.db.models import Q


def term_for_date(establishment, school_year, target_date):
    """Renvoie le Term de cet établissement/année scolaire dont la plage
    couvre `target_date`, ou None si la date tombe dans un trou entre deux
    trimestres (ou avant le premier / après le dernier) — c'est-à-dire en
    vacances."""
    from apps.grading.models import Term

    return Term.objects.filter(
        establishment=establishment,
        school_year=school_year,
        start_date__lte=target_date,
        end_date__gte=target_date,
    ).order_by("start_date").first()


def is_holiday(establishment, school_class, target_date):
    """Un jour férié ponctuel a-t-il été déclaré pour cette date, sur cette
    classe (ou tout l'établissement) ? Distinct des vacances déduites des
    trimestres (term_for_date) : un jour férié ne fait JAMAIS sortir la
    date de la plage de son trimestre pour le reste du système — seule
    l'affichage des cours officiels de ce jour précis est neutralisé (voir
    timetable_slots_for_date, seul endroit qui combine les deux)."""
    from django.db.models import Q as _Q

    from .models import EstablishmentEvent, EventType

    return EstablishmentEvent.objects.filter(
        establishment=establishment, event_type=EventType.HOLIDAY, date=target_date,
    ).filter(_Q(school_class__isnull=True) | _Q(school_class=school_class)).exists()


def timetable_slots_for_date(school_class, target_date):
    """Créneaux officiels de `school_class` réellement actifs à
    `target_date` : le bon jour de la semaine, ET (aucun trimestre assigné
    au créneau => valable toute l'année scolaire, mais seulement si la date
    tombe dans un trimestre existant ; OU le créneau est assigné
    précisément au trimestre courant). Renvoie un queryset vide si la date
    est un dimanche, tombe en vacances, ou est déclarée jour férié pour
    cette classe (voir is_holiday — la date reste un jour d'école pour le
    reste du système, seul cet affichage est vidé)."""
    from .models import TimetableSlot

    weekday = target_date.weekday()
    if weekday > 5:
        return TimetableSlot.objects.none()

    establishment = school_class.track.department.establishment
    term = term_for_date(establishment, school_class.school_year, target_date)
    if term is None:
        return TimetableSlot.objects.none()

    if is_holiday(establishment, school_class, target_date):
        return TimetableSlot.objects.none()

    return TimetableSlot.objects.filter(
        school_class=school_class, weekday=weekday
    ).filter(Q(term__isnull=True) | Q(term=term)).select_related("subject")


def events_for_date(establishment, school_class, target_date, audience_role):
    """Événements d'établissement pertinents pour `target_date`, sur cette
    classe (ou déclarés pour tout l'établissement), et dont le public
    cible inclut `audience_role` ("students", "parents" ou "teachers") —
    seule fonction qui filtre les événements par audience, réutilisée par
    l'agenda élève et l'agenda parent, jamais dupliquée."""
    from .models import EstablishmentEvent

    events = EstablishmentEvent.objects.filter(
        establishment=establishment, date=target_date,
    ).filter(Q(school_class__isnull=True) | Q(school_class=school_class)).order_by("start_time")
    return [e for e in events if audience_role in (e.audience or [])]


def personal_blocks_for_date(child, target_date):
    """Créneaux personnels (règle + exception éventuelle du jour) d'un
    élève pour `target_date`, tous jours confondus (dimanche inclus).
    Renvoie une liste de dicts prêts à sérialiser, une occurrence annulée
    ce jour-là étant simplement absente du résultat."""
    from .models import PersonalScheduleBlock, PersonalScheduleException

    weekday = target_date.weekday()
    blocks = PersonalScheduleBlock.objects.filter(
        child=child, weekday=weekday, valid_from__lte=target_date,
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=target_date)
    ).select_related("subject")

    exceptions = {
        exc.block_id: exc
        for exc in PersonalScheduleException.objects.filter(block__in=blocks, date=target_date).select_related("subject")
    }

    result = []
    for block in blocks:
        exc = exceptions.get(block.id)
        if exc and exc.is_cancelled:
            continue
        if exc:
            subject = exc.subject if exc.subject_id else block.subject
            result.append({
                "block": block.id,
                "exception": exc.id,
                "title": exc.title or block.title,
                "subject": subject.id if subject else None,
                "subject_name": subject.name if subject else None,
                "start_time": exc.start_time or block.start_time,
                "end_time": exc.end_time or block.end_time,
            })
        else:
            result.append({
                "block": block.id,
                "exception": None,
                "title": block.title,
                "subject": block.subject_id,
                "subject_name": block.subject.name if block.subject_id else None,
                "start_time": block.start_time,
                "end_time": block.end_time,
            })
    return result
