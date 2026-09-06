"""
Xporadia — apps/virtual_classes/services.py

Logique partagée entre les points d'entrée de création de devoir : l'écran
dédié historique (apps.virtual_classes.views) et la création directe
depuis le canal de matière (apps.messaging.views).
"""
from apps.academics.models import Enrollment, EnrollmentStatus


def notify_enrolled_parents(school_class, notif_type, title, body):
    from apps.notifications.services import notify_user

    notified_parent_ids = set()
    enrollments = Enrollment.objects.filter(
        school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).select_related("child__parent__user")
    for enrollment in enrollments:
        if not enrollment.child.parent_id:
            continue  # élève auto-inscrit sans parent rattaché
        parent_user = enrollment.child.parent.user
        if parent_user.id in notified_parent_ids:
            continue
        notified_parent_ids.add(parent_user.id)
        notify_user(parent_user, notif_type, title=title, body=body)
