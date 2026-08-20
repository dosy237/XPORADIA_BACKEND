"""
Xporadia — apps/messaging/services.py

Toute la logique "qui est membre de quel canal, et quand ça se crée" vit
ici plutôt que dispersée dans des signaux Django — plus facile à tester et
à raisonner pour un système aussi sensible (élèves mineurs, messageries
privées) qu'une messagerie.
"""
from .models import Channel, ChannelMembership, ChannelType


def get_or_create_class_channel(school_class):
    channel, created = Channel.objects.get_or_create(
        channel_type=ChannelType.CLASS,
        school_class=school_class,
        defaults={"created_by": school_class.homeroom_teacher},
    )
    if school_class.homeroom_teacher_id:
        ChannelMembership.objects.get_or_create(
            channel=channel, user=school_class.homeroom_teacher, defaults={"is_admin": True}
        )
    return channel


def get_or_create_direct_channel(user_a, user_b):
    """Renvoie le canal DM existant entre ces deux utilisateurs, ou en
    crée un — jamais de doublon (une seule DM par paire)."""
    existing = (
        Channel.objects.filter(channel_type=ChannelType.DIRECT, memberships__user=user_a)
        .filter(memberships__user=user_b)
        .first()
    )
    if existing:
        return existing

    channel = Channel.objects.create(channel_type=ChannelType.DIRECT)
    ChannelMembership.objects.bulk_create(
        [
            ChannelMembership(channel=channel, user=user_a),
            ChannelMembership(channel=channel, user=user_b),
        ]
    )
    return channel


def _active_enrolled_student_users(school_class):
    """Comptes élèves activés (Child.user renseigné) actuellement inscrits
    et actifs dans cette classe."""
    from apps.academics.models import Enrollment, EnrollmentStatus

    return [
        e.child.user
        for e in Enrollment.objects.filter(
            school_class=school_class, status=EnrollmentStatus.ACTIVE, child__user__isnull=False
        ).select_related("child__user")
    ]


def create_subject_channel(subject, creator):
    """Action explicite de l'enseignant dédié — jamais automatique. Peuple
    immédiatement avec les élèves actuellement inscrits dans la classe."""
    channel = Channel.objects.create(
        channel_type=ChannelType.SUBJECT, subject=subject, created_by=creator
    )
    ChannelMembership.objects.get_or_create(channel=channel, user=creator, defaults={"is_admin": True})
    for student_user in _active_enrolled_student_users(subject.school_class):
        ChannelMembership.objects.get_or_create(channel=channel, user=student_user)
    return channel


def ensure_teacher_dm_channels(subject):
    """Appelée quand un enseignant devient (ou redevient) dédié d'une
    matière : ouvre une DM avec chaque élève déjà activé de la classe.
    Idempotente — sûre à rappeler à chaque changement d'affectation."""
    if not subject.teacher_id:
        return
    for student_user in _active_enrolled_student_users(subject.school_class):
        get_or_create_direct_channel(subject.teacher, student_user)


def ensure_student_messaging(child):
    """Appelée une fois à l'activation du compte élève (StudentActivation) :
    rejoint le canal de chaque classe où il a une inscription active, tous
    les canaux de matière déjà créés pour ces classes, et ouvre une DM avec
    chaque enseignant déjà dédié d'une matière de ces classes."""
    from apps.academics.models import Enrollment, EnrollmentStatus

    if not child.user_id:
        return

    enrollments = Enrollment.objects.filter(
        child=child, status=EnrollmentStatus.ACTIVE
    ).select_related("school_class")

    for enrollment in enrollments:
        school_class = enrollment.school_class
        class_channel = get_or_create_class_channel(school_class)
        ChannelMembership.objects.get_or_create(channel=class_channel, user=child.user)

        subject_channels = Channel.objects.filter(
            channel_type=ChannelType.SUBJECT, subject__school_class=school_class
        )
        for channel in subject_channels:
            ChannelMembership.objects.get_or_create(channel=channel, user=child.user)

        for subject in school_class.subjects.filter(teacher__isnull=False).select_related("teacher"):
            get_or_create_direct_channel(subject.teacher, child.user)


def ensure_internship_channel(convention):
    """Ouvre le canal de stage à la signature complète de la convention —
    seulement si l'élève a déjà activé son propre compte (sinon rien à
    créer, on ne peut pas ouvrir de messagerie sans compte destinataire)."""
    student = convention.application.student
    if not student.user_id:
        return None

    channel, created = Channel.objects.get_or_create(
        channel_type=ChannelType.INTERNSHIP, internship_convention=convention
    )
    company_id = convention.application.offer.company_id
    ChannelMembership.objects.get_or_create(channel=channel, user_id=company_id)
    ChannelMembership.objects.get_or_create(channel=channel, user=student.user)
    return channel


def archive_internship_channel(convention):
    Channel.objects.filter(internship_convention=convention).update(is_archived=True)


def save_uploaded_attachments(files, request, upload_to="message_attachments"):
    """Enregistre des fichiers réellement transférés (photos, PDF...) et
    renvoie la liste {name, url, type} attendue par les champs `attachments`
    (Message, Exercise, Submission) — jamais des URL fournies telles
    quelles par le client, toujours des fichiers effectivement reçus et
    stockés côté serveur, comme partout ailleurs dans le projet (avatar,
    couverture/PDF de bibliothèque)."""
    from django.core.files.storage import default_storage

    attachments = []
    for f in files:
        path = default_storage.save(f"{upload_to}/{f.name}", f)
        url = default_storage.url(path)
        attachments.append({
            "name": f.name,
            "url": request.build_absolute_uri(url) if request else url,
            "type": f.content_type or "",
        })
    return attachments


def notify_channel_members(channel, message, request, preview_override=None):
    """Notifie les autres membres d'un canal qu'un nouveau message vient
    d'être posté — factorisé pour être appelé aussi bien depuis l'envoi de
    message normal que depuis la publication d'un devoir ou d'une
    soumission (voir apps.messaging.views)."""
    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify_user

    from .serializers import ChannelSerializer

    recipients = ChannelMembership.objects.filter(channel=channel).exclude(
        user=message.author
    ).select_related("user")
    preview = preview_override or (message.body[:80] if message.body else "Pièce jointe envoyée")
    author_name = message.author.get_full_name()
    # Pour un canal collectif, on précise lequel dans le titre ; pour un
    # message privé, le nom de l'auteur suffit (le destinataire sait déjà
    # que c'est une conversation 1:1).
    if channel.channel_type != ChannelType.DIRECT:
        channel_name = ChannelSerializer(channel, context={"request": request}).data["display_name"]
        title = f"{author_name} — {channel_name}"
    else:
        title = author_name
    for membership in recipients:
        notify_user(
            membership.user,
            NotificationType.NEW_MESSAGE,
            title=title,
            body=preview,
            data={"channel_id": channel.id},
        )
