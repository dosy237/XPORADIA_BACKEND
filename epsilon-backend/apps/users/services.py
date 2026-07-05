"""
Xporadia — Génération et envoi des codes OTP de vérification de compte.
En dev : envoyé par email (console backend) et loggé comme SMS simulé.
À remplacer par Twilio (SMS) en production — voir EP-08 US-08-02.
"""
import logging
import random
from datetime import timedelta

from django.core.mail import send_mail
from django.utils import timezone

from .models import OTPCode, OTPPurpose

logger = logging.getLogger(__name__)

OTP_VALIDITY_MINUTES = 15


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
    send_mail(
        subject="Xporadia — Votre code de vérification",
        message=f"Votre code de vérification Xporadia est : {code} (valable {OTP_VALIDITY_MINUTES} min).",
        from_email=None,
        recipient_list=[user.email],
        fail_silently=True,
    )
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
