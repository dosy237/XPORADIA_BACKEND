"""
Xporadia — apps/notifications/constants.py

Rattache chaque NotificationType à l'une des 4 grandes catégories
réglables par l'utilisateur (voir NotificationCategory). L'assertion en
bas de fichier garantit qu'un futur NotificationType ajouté sans être
catégorisé ici est détecté au démarrage plutôt que de contourner
silencieusement les préférences de notification.
"""
from .models import NotificationCategory, NotificationType

CATEGORY_BY_NOTIF_TYPE = {
    # Scolarité de l'élève
    NotificationType.EXAM_AVAILABLE: NotificationCategory.SCHOOL_LIFE,
    NotificationType.EXAM_RESULT: NotificationCategory.SCHOOL_LIFE,
    NotificationType.SESSION_CONFIRMED: NotificationCategory.SCHOOL_LIFE,
    NotificationType.SESSION_CANCELLED: NotificationCategory.SCHOOL_LIFE,
    NotificationType.EXERCISE_PUBLISHED: NotificationCategory.SCHOOL_LIFE,
    NotificationType.EXERCISE_SUBMITTED: NotificationCategory.SCHOOL_LIFE,
    NotificationType.EXERCISE_DUE_SOON: NotificationCategory.SCHOOL_LIFE,
    NotificationType.EXERCISE_OVERDUE: NotificationCategory.SCHOOL_LIFE,
    NotificationType.CORRECTION_READY: NotificationCategory.SCHOOL_LIFE,
    NotificationType.CERT_EXPIRY: NotificationCategory.SCHOOL_LIFE,
    NotificationType.CERT_LEVEL_CHANGED: NotificationCategory.SCHOOL_LIFE,
    NotificationType.REPORT_CARD_PUBLISHED: NotificationCategory.SCHOOL_LIFE,
    NotificationType.TIMETABLE_REMINDER: NotificationCategory.SCHOOL_LIFE,
    NotificationType.REVISION_REMINDER: NotificationCategory.SCHOOL_LIFE,
    NotificationType.NEW_CERT_MODULE: NotificationCategory.SCHOOL_LIFE,
    NotificationType.HOLIDAY_DECLARED: NotificationCategory.SCHOOL_LIFE,
    # Emploi
    NotificationType.NEW_JOB_OFFER: NotificationCategory.EMPLOYMENT,
    NotificationType.APPLICATION_VIEWED: NotificationCategory.EMPLOYMENT,
    NotificationType.RECRUITMENT: NotificationCategory.EMPLOYMENT,
    NotificationType.STAGE_UPDATE: NotificationCategory.EMPLOYMENT,
    NotificationType.PAYMENT_RECEIVED: NotificationCategory.EMPLOYMENT,
    NotificationType.INVOICE_READY: NotificationCategory.EMPLOYMENT,
    # Messagerie
    NotificationType.NEW_MESSAGE: NotificationCategory.MESSAGING,
    NotificationType.FOLLOWED_USER_POST: NotificationCategory.MESSAGING,
    # Administratif
    NotificationType.CLASS_ASSIGNMENT: NotificationCategory.ADMINISTRATIVE,
    NotificationType.ENROLLMENT_UPDATE: NotificationCategory.ADMINISTRATIVE,
    NotificationType.CLAIM_REQUEST_REVIEWED: NotificationCategory.ADMINISTRATIVE,
    NotificationType.ENGAGEMENT_TIP: NotificationCategory.ADMINISTRATIVE,
    NotificationType.SYSTEM: NotificationCategory.ADMINISTRATIVE,
}

assert set(CATEGORY_BY_NOTIF_TYPE) == set(NotificationType.values), (
    "Chaque NotificationType doit être rattaché à une NotificationCategory dans CATEGORY_BY_NOTIF_TYPE."
)
