"""
Xporadia — apps/payments/services.py

En dev : les paiements Mobile Money sont simulés — confirmation et
libération d'escrow immédiates et journalisées, sans intégration
opérateur réelle. À remplacer par les webhooks Orange Money / Wave /
MTN MoMo en production (même logique que le simulateur OTP/SMS —
voir apps/users/services.py).
"""
import logging
import secrets

from django.utils import timezone

from .models import Payment, PaymentStatus

logger = logging.getLogger(__name__)


def initiate_payment(user, amount, operator, phone_number, payment_type, content_object):
    return Payment.objects.create(
        user=user,
        amount=amount,
        operator=operator,
        phone_number=phone_number,
        payment_type=payment_type,
        content_object=content_object,
        tx_ref=f"XPO-PAY-{secrets.token_hex(8).upper()}",
    )


def confirm_payment_to_escrow(payment):
    logger.info(
        "Paiement Mobile Money simulé : %s — %s FCFA via %s séquestrés.",
        payment.tx_ref, payment.amount, payment.operator,
    )
    payment.status = PaymentStatus.ESCROW
    payment.operator_tx_id = f"SIM-{secrets.token_hex(6).upper()}"
    payment.save(update_fields=["status", "operator_tx_id"])
    return payment


def release_escrow(payment):
    payment.status = PaymentStatus.COMPLETED
    payment.completed_at = timezone.now()
    payment.save(update_fields=["status", "completed_at"])
    return payment


def refund_payment(payment):
    payment.status = PaymentStatus.REFUNDED
    payment.completed_at = timezone.now()
    payment.save(update_fields=["status", "completed_at"])
    return payment
