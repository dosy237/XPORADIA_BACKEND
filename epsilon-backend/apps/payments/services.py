"""
Xporadia — apps/payments/services.py

En dev : les paiements sont simulés — confirmation et libération d'escrow
immédiates et journalisées, sans intégration opérateur/bancaire réelle.
Deux moyens de paiement : Mobile Money (à remplacer par les webhooks
Orange Money / Wave / MTN MoMo en production) et carte bancaire (à
remplacer par une passerelle réelle — Stripe, CinetPay, etc. — le moment
venu). Même logique que le simulateur OTP/SMS — voir apps/users/services.py.
"""
import logging
import secrets

from django.utils import timezone

from .models import Payment, PaymentMethod, PaymentStatus

logger = logging.getLogger(__name__)


def initiate_payment(user, amount, payment_type, operator=None, phone_number=None,
                      card_last4=None, card_holder_name=None, content_object=None):
    method = PaymentMethod.BANK_CARD if card_last4 else PaymentMethod.MOBILE_MONEY
    return Payment.objects.create(
        user=user,
        amount=amount,
        method=method,
        operator=operator or "",
        phone_number=phone_number or "",
        card_last4=card_last4 or "",
        card_holder_name=card_holder_name or "",
        payment_type=payment_type,
        content_object=content_object,
        tx_ref=f"XPO-PAY-{secrets.token_hex(8).upper()}",
    )


def confirm_payment_to_escrow(payment):
    logger.info(
        "Paiement simulé (%s) : %s — %s FCFA séquestrés.",
        payment.get_method_display(), payment.tx_ref, payment.amount,
    )
    payment.status = PaymentStatus.ESCROW
    payment.operator_tx_id = f"SIM-{secrets.token_hex(6).upper()}"
    payment.save(update_fields=["status", "operator_tx_id"])
    return payment


def confirm_payment_completed(payment):
    """Paiements sans contrepartie à séquestrer (formation, facture de
    paie...) : la somme va directement à la plateforme Xporadia, pas de
    libération future."""
    logger.info(
        "Paiement simulé (%s) : %s — %s FCFA complété.",
        payment.get_method_display(), payment.tx_ref, payment.amount,
    )
    payment.status = PaymentStatus.COMPLETED
    payment.operator_tx_id = f"SIM-{secrets.token_hex(6).upper()}"
    payment.completed_at = timezone.now()
    payment.save(update_fields=["status", "operator_tx_id", "completed_at"])

    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify_user
    from apps.users.models import User, UserRole

    for admin in User.objects.filter(primary_role=UserRole.ADMIN, is_active=True):
        notify_user(
            admin, NotificationType.PAYMENT_RECEIVED,
            title="Paiement reçu",
            body=f"{payment.amount} FCFA reçus de {payment.user.get_full_name()} "
                 f"({payment.get_payment_type_display()}, {payment.get_method_display()}).",
            data={"payment_id": str(payment.id)},
        )
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
