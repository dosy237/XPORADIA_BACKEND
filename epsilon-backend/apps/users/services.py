"""
Xporadia — Génération et envoi des codes OTP de vérification de compte.
En dev : envoyé par email (console backend) et loggé comme SMS simulé.
À remplacer par Twilio (SMS) en production — voir EP-08 US-08-02.
"""
import logging
import random
from datetime import timedelta

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from .models import OTPCode, OTPPurpose

logger = logging.getLogger(__name__)

OTP_VALIDITY_MINUTES = 15


def establishment_summary(director_profile):
    """Chiffres réels d'un établissement — effectif actif et demandes de
    rattachement en attente — jamais un champ stocké séparément qui
    pourrait diverger (voir DirectorProfile.student_count, un simple
    effectif déclaré à l'inscription, jamais utilisé ici). Imports
    différés : apps.academics et apps.grading importent déjà apps.users
    au niveau module, un import direct ici créerait un cycle."""
    from apps.academics.models import Enrollment, EnrollmentStatus
    from apps.grading.models import EstablishmentJoinRequest, JoinRequestStatus

    student_count = Enrollment.objects.filter(
        school_class__track__department__establishment=director_profile,
        status=EnrollmentStatus.ACTIVE,
    ).count()
    pending_join_requests = EstablishmentJoinRequest.objects.filter(
        establishment=director_profile, status=JoinRequestStatus.PENDING
    ).count()
    return {"student_count": student_count, "pending_join_requests": pending_join_requests}


def generate_otp(user, purpose: str = OTPPurpose.ACCOUNT_VERIFICATION) -> OTPCode:
    code = f"{random.randint(0, 999999):06d}"
    otp = OTPCode.objects.create(
        user=user,
        code=code,
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=OTP_VALIDITY_MINUTES),
    )
    _deliver_otp(user, code)
    return otp


def _deliver_otp(user, code: str) -> None:
    html_body = render_to_string(
        "emails/otp_verification.html",
        {
            "first_name": user.first_name,
            "code": code,
            "validity_minutes": OTP_VALIDITY_MINUTES,
        },
    )
    message = EmailMultiAlternatives(
        subject="Xporadia — Votre code de vérification",
        body=strip_tags(html_body),
        from_email=None,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=True)
    logger.info("SMS simulé vers %s : code de vérification Xporadia %s", user.phone or "(pas de téléphone)", code)


def verify_otp(user, code: str, purpose: str = OTPPurpose.ACCOUNT_VERIFICATION) -> bool:
    otp = (
        OTPCode.objects.filter(user=user, code=code, purpose=purpose, used=False)
        .order_by("-created_at")
        .first()
    )
    if not otp or not otp.is_valid():
        return False
    otp.used = True
    otp.save(update_fields=["used"])
    return True
