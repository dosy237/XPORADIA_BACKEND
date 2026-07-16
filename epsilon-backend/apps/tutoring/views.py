from django.http import Http404
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.payments.models import MobileOperator, PaymentType
from apps.payments.services import confirm_payment_to_escrow, initiate_payment, refund_payment, release_escrow
from apps.users.models import TeacherProfile, UserRole

from .models import TutoringReview, TutoringSession, TutoringSessionStatus
from .serializers import TutoringReviewSerializer, TutoringSessionSerializer, TutoringSessionStatusSerializer


def _require_parent(user):
    if not user.has_role(UserRole.PARENT):
        raise PermissionDenied("Réservé aux parents.")


class MyTutoringSessionsView(generics.ListCreateAPIView):
    """Réservations de cours particuliers — le parent réserve un enseignant
    « disponible cours particuliers » et paie immédiatement (Mobile Money
    séquestré), l'enseignant est notifié de la nouvelle réservation."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TutoringSessionSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if user.has_role(UserRole.PARENT):
            qs = TutoringSession.objects.filter(parent=user)
        else:
            qs = TutoringSession.objects.filter(teacher=user)
        return qs.select_related("teacher", "parent").prefetch_related("payments")

    def perform_create(self, serializer):
        user = self.request.user
        _require_parent(user)
        teacher = serializer.validated_data["teacher"]
        try:
            teacher_profile = teacher.teacher_profile
        except TeacherProfile.DoesNotExist:
            raise ValidationError("Cet enseignant n'a pas de profil de cours particuliers.")
        if not teacher_profile.available_for_tutoring:
            raise ValidationError("Cet enseignant n'est pas disponible pour les cours particuliers.")

        operator = self.request.data.get("operator")
        phone_number = self.request.data.get("phone_number")
        if operator not in MobileOperator.values or not phone_number:
            raise ValidationError("Opérateur Mobile Money et numéro de téléphone requis.")

        gross_amount = teacher_profile.hourly_rate
        if not gross_amount:
            raise ValidationError("Cet enseignant n'a pas encore renseigné son tarif horaire.")

        session = serializer.save(parent=user, gross_amount=int(gross_amount))

        payment = initiate_payment(
            user=user, amount=int(gross_amount), operator=operator, phone_number=phone_number,
            payment_type=PaymentType.TUTORING, content_object=session,
        )
        confirm_payment_to_escrow(payment)
        session.status = TutoringSessionStatus.CONFIRMED
        session.confirmed_at = timezone.now()
        session.save(update_fields=["status", "confirmed_at"])

        notify_user(
            teacher,
            NotificationType.SESSION_CONFIRMED,
            title="Nouvelle réservation de cours particulier",
            body=f"{user.get_full_name()} a réservé une séance de {session.subject} le {session.date}.",
        )


class TutoringSessionDetailView(generics.RetrieveUpdateAPIView):
    """Détail d'une séance — le parent ou l'enseignant concerné peut la
    marquer terminée (libère l'escrow au profit de l'enseignant) ou
    annulée (rembourse le parent)."""

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return TutoringSessionStatusSerializer
        return TutoringSessionSerializer

    def get_queryset(self):
        return TutoringSession.objects.select_related("teacher", "parent").prefetch_related("payments")

    def get_object(self):
        try:
            session = self.get_queryset().get(pk=self.kwargs["pk"])
        except TutoringSession.DoesNotExist:
            raise Http404
        user = self.request.user
        if user.id not in (session.teacher_id, session.parent_id):
            raise PermissionDenied("Réservé aux personnes concernées par cette séance.")
        return session

    def perform_update(self, serializer):
        session = serializer.instance
        user = self.request.user
        new_status = serializer.validated_data.get("status")

        if session.status not in (TutoringSessionStatus.PENDING, TutoringSessionStatus.CONFIRMED):
            raise PermissionDenied("Cette séance ne peut plus changer de statut.")

        payment = session.payments.order_by("-created_at").first()

        if new_status == "completed":
            if user.id != session.teacher_id:
                raise PermissionDenied("Seul l'enseignant peut marquer la séance comme terminée.")
            session = serializer.save(status=TutoringSessionStatus.COMPLETED)
            if payment:
                release_escrow(payment)
                session.escrow_released = True
                session.released_at = timezone.now()
                session.save(update_fields=["escrow_released", "released_at"])
            notify_user(
                session.parent,
                NotificationType.SESSION_CONFIRMED,
                title="Séance terminée",
                body=f"La séance de {session.subject} du {session.date} a été marquée terminée. Vous pouvez laisser un avis.",
            )
            notify_user(
                session.teacher,
                NotificationType.PAYMENT_RECEIVED,
                title="Paiement libéré",
                body=f"Le paiement de {session.net_amount} FCFA pour la séance de {session.subject} a été libéré.",
            )
        else:
            session = serializer.save(
                status=TutoringSessionStatus.CANCELLED, cancelled_at=timezone.now()
            )
            if payment:
                refund_payment(payment)
            other = session.teacher if user.id == session.parent_id else session.parent
            notify_user(
                other,
                NotificationType.SESSION_CANCELLED,
                title="Séance annulée",
                body=f"La séance de {session.subject} du {session.date} a été annulée.",
            )


class SessionReviewsView(generics.ListCreateAPIView):
    """Avis laissé par le parent après une séance terminée."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TutoringReviewSerializer
    pagination_class = None

    def _get_session(self):
        try:
            return TutoringSession.objects.get(id=self.kwargs["session_id"])
        except TutoringSession.DoesNotExist:
            raise Http404

    def get_queryset(self):
        return TutoringReview.objects.filter(session=self._get_session())

    def perform_create(self, serializer):
        session = self._get_session()
        user = self.request.user
        if user.id != session.parent_id:
            raise PermissionDenied("Réservé au parent de cette séance.")
        if session.status != TutoringSessionStatus.COMPLETED:
            raise PermissionDenied("La séance doit être terminée avant de laisser un avis.")
        if TutoringReview.objects.filter(session=session, author=user).exists():
            raise ValidationError("Vous avez déjà laissé un avis pour cette séance.")
        serializer.save(session=session, author=user, author_type="parent")
