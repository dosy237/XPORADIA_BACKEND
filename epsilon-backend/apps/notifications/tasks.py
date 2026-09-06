"""
Xporadia — apps/notifications/tasks.py

Nudges quotidiens d'engagement : un rappel personnalisé par compte pour
l'aider à progresser en visibilité (points de certification pour un
enseignant, activité récente pour un établissement ou une entreprise) — le
même principe que les rappels "continue ta progression" des réseaux sociaux.

Nécessite un worker ET un beat Celery actifs pour s'exécuter réellement
(voir CELERY_BEAT_SCHEDULE dans config/settings/base.py) : sans eux, cette
tâche existe mais ne se déclenche jamais toute seule. Un envoi par compte
et par jour maximum (voir _already_nudged_today) — évite les doublons si le
beat est relancé ou la tâche rejouée manuellement.
"""
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Notification, NotificationType
from .services import notify_user

ENGAGEMENT_NUDGE_MIN_GAP_HOURS = 20
INACTIVITY_WINDOW_DAYS = 14


def _already_nudged_today(user):
    cutoff = timezone.now() - timedelta(hours=ENGAGEMENT_NUDGE_MIN_GAP_HOURS)
    return Notification.objects.filter(
        user=user, notif_type=NotificationType.ENGAGEMENT_TIP, created_at__gte=cutoff
    ).exists()


@shared_task(ignore_result=True)
def send_daily_engagement_nudges():
    _nudge_teachers()
    _nudge_establishments()
    _nudge_companies()


def _nudge_teachers():
    """Un enseignant encore loin du palier suivant reçoit un rappel — celui
    déjà au niveau maximum (Diamant) n'a rien à atteindre, donc rien à
    envoyer."""
    from apps.certification.constants import points_to_next_level
    from apps.certification.services import teacher_total_points
    from apps.users.models import User, UserRole

    teachers = User.objects.filter(
        primary_role=UserRole.TEACHER, is_active=True, is_documents_validated=True
    )
    for user in teachers:
        if _already_nudged_today(user):
            continue
        next_info = points_to_next_level(teacher_total_points(user))
        if not next_info:
            continue
        notify_user(
            user,
            NotificationType.ENGAGEMENT_TIP,
            title="Encore un peu d'effort !",
            body=(
                f"Il te manque {next_info['points_needed']} points pour atteindre le niveau "
                f"{next_info['next_level']}. Valide une nouvelle certification pour progresser."
            ),
            data={"kind": "teacher_points"},
        )


def _nudge_establishments():
    """Un établissement resté silencieux sur le fil depuis deux semaines
    reçoit un rappel — la visibilité de l'annuaire dépend directement de
    cette activité (voir apps.users.views._annotate_establishment_activity)."""
    from apps.feed.models import Post
    from apps.users.models import User, UserRole

    since = timezone.now() - timedelta(days=INACTIVITY_WINDOW_DAYS)
    directors = User.objects.filter(
        primary_role=UserRole.DIRECTOR, is_active=True, is_documents_validated=True
    )
    for user in directors:
        if _already_nudged_today(user):
            continue
        if Post.objects.filter(author=user, created_at__gte=since).exists():
            continue
        notify_user(
            user,
            NotificationType.ENGAGEMENT_TIP,
            title="Faites connaître votre établissement",
            body="Publier une actualité régulièrement augmente la visibilité de votre établissement dans l'annuaire.",
            data={"kind": "establishment_activity"},
        )


def _nudge_companies():
    """Symétrique côté entreprise : sans offre active ni publication
    récente, l'entreprise reste invisible dans le catalogue et l'annuaire."""
    from apps.feed.models import Post
    from apps.internships.models import InternshipOffer
    from apps.users.models import User, UserRole

    since = timezone.now() - timedelta(days=INACTIVITY_WINDOW_DAYS)
    companies = User.objects.filter(
        primary_role=UserRole.COMPANY, is_active=True, is_documents_validated=True
    )
    for user in companies:
        if _already_nudged_today(user):
            continue
        has_active_offer = InternshipOffer.objects.filter(company=user, is_active=True).exists()
        has_recent_post = Post.objects.filter(author=user, created_at__gte=since).exists()
        if has_active_offer and has_recent_post:
            continue
        body = (
            "Publiez une offre de stage pour gagner en visibilité auprès des établissements partenaires."
            if not has_active_offer
            else "Publier une actualité régulièrement augmente votre visibilité dans l'annuaire."
        )
        notify_user(
            user,
            NotificationType.ENGAGEMENT_TIP,
            title="Gagnez en visibilité",
            body=body,
            data={"kind": "company_activity"},
        )
