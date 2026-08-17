from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Channel, ChannelMembership, ChannelType, Message
from .realtime import broadcast_to_channel
from .serializers import ChannelSerializer, CreateMessageSerializer, EditMessageSerializer, MessageSerializer


class IsVerifiedToMessage(permissions.BasePermission):
    """Même règle que le fil d'actualité : un compte non vérifié peut lire
    mais pas écrire — cohérence de la plateforme, et garde-fou contre les
    comptes jetables dans un espace qui inclut des élèves mineurs."""

    message = "Vérifiez votre compte avant d'envoyer un message."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_verified)


class ChannelListView(generics.ListAPIView):
    """Mes canaux — classe(s), matières rejointes, messages privés, stage —
    triés par activité la plus récente. Pour un directeur, inclut aussi
    les canaux de classe de son établissement en modération (lecture
    seule, jamais les matières/messages privés/stages)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChannelSerializer
    pagination_class = None

    def get_queryset(self):
        from django.db.models import Q

        from apps.users.models import UserRole

        user = self.request.user
        filters = Q(memberships__user=user)
        if user.has_role(UserRole.DIRECTOR):
            filters |= Q(
                channel_type=ChannelType.CLASS,
                school_class__track__department__establishment__user=user,
            )
        return Channel.objects.filter(filters).distinct().order_by("-messages__created_at", "-created_at")


def _require_membership(channel, user):
    if not ChannelMembership.objects.filter(channel=channel, user=user).exists():
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Vous n'êtes pas membre de ce canal.")


def _director_moderates_class_channel(channel, user) -> bool:
    """Le directeur d'un établissement peut consulter (jamais écrire) le
    canal de CLASSE de son propre établissement — garde-fou de sécurité
    pour un public mineur. N'accorde jamais l'accès aux canaux de matière,
    messages privés, ou canaux de stage : uniquement le canal de classe."""
    from apps.users.models import UserRole

    if channel.channel_type != ChannelType.CLASS or not user.has_role(UserRole.DIRECTOR):
        return False
    return channel.school_class.track.department.establishment.user_id == user.id


def _require_read_access(channel, user):
    """Lecture — membre du canal, ou directeur en modération d'un canal
    de classe de son établissement."""
    if ChannelMembership.objects.filter(channel=channel, user=user).exists():
        return
    if _director_moderates_class_channel(channel, user):
        return
    from rest_framework.exceptions import PermissionDenied

    raise PermissionDenied("Vous n'avez pas accès à ce canal.")


class ChannelMessagesView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsVerifiedToMessage]

    def get_channel(self):
        return get_object_or_404(Channel, pk=self.kwargs["channel_id"])

    def get_queryset(self):
        channel = self.get_channel()
        _require_read_access(channel, self.request.user)
        return Message.objects.filter(channel=channel).select_related("author").order_by("created_at")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreateMessageSerializer
        return MessageSerializer

    def perform_create(self, serializer):
        channel = self.get_channel()
        _require_membership(channel, self.request.user)
        if channel.is_archived:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Ce canal est archivé (lecture seule).")
        message = serializer.save(channel=channel, author=self.request.user)
        self._notify_other_members(channel, message)
        broadcast_to_channel(
            channel.id, "message_created",
            {"message": MessageSerializer(message, context={"request": self.request}).data},
        )

    def _notify_other_members(self, channel, message):
        from apps.notifications.models import NotificationType
        from apps.notifications.services import notify_user

        from .models import ChannelType

        recipients = ChannelMembership.objects.filter(channel=channel).exclude(
            user=message.author
        ).select_related("user")
        preview = message.body[:80] if message.body else "Pièce jointe envoyée"
        author_name = message.author.get_full_name()
        # Pour un canal collectif, on précise lequel dans le titre ; pour un
        # message privé, le nom de l'auteur suffit (le destinataire sait
        # déjà que c'est une conversation 1:1).
        if channel.channel_type != ChannelType.DIRECT:
            from .serializers import ChannelSerializer

            channel_name = ChannelSerializer(channel, context={"request": self.request}).data["display_name"]
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

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            MessageSerializer(serializer.instance, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MarkChannelReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, channel_id):
        membership = get_object_or_404(ChannelMembership, channel_id=channel_id, user=request.user)
        membership.last_read_at = timezone.now()
        membership.save(update_fields=["last_read_at"])
        return Response({"detail": "Canal marqué comme lu."})


class MessageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Modification/suppression d'un message, réservée à son auteur.
    Modifiable sans limite de temps (comme Telegram : un badge « modifié »
    reste affiché, plutôt qu'une fenêtre d'édition arbitraire)."""

    permission_classes = [permissions.IsAuthenticated]
    queryset = Message.objects.select_related("author", "channel")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return EditMessageSerializer
        return MessageSerializer

    def get_object(self):
        message = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        if message.author_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Vous ne pouvez modifier que vos propres messages.")
        return message

    def perform_update(self, serializer):
        message = serializer.save(is_edited=True)
        broadcast_to_channel(
            message.channel_id, "message_updated",
            {"message": MessageSerializer(message, context={"request": self.request}).data},
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(MessageSerializer(instance, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        channel_id = instance.channel_id
        message_id = instance.id
        response = super().destroy(request, *args, **kwargs)
        broadcast_to_channel(channel_id, "message_deleted", {"message_id": message_id})
        return response


class CreateSubjectChannelView(APIView):
    """L'enseignant dédié crée le canal d'échange public de sa matière —
    jamais automatique, c'est un choix pédagogique délibéré."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, subject_id):
        from apps.academics.models import Subject

        from .services import create_subject_channel

        subject = get_object_or_404(Subject, pk=subject_id)
        if subject.teacher_id != request.user.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")
        if Channel.objects.filter(channel_type=ChannelType.SUBJECT, subject=subject).exists():
            return Response({"detail": "Ce canal existe déjà."}, status=status.HTTP_400_BAD_REQUEST)

        channel = create_subject_channel(subject, request.user)
        return Response(
            ChannelSerializer(channel, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


class ContactChildTeacherView(APIView):
    """Ouvre (ou retrouve) une conversation directe entre un parent et un
    enseignant — restreint à un enseignant qui enseigne RÉELLEMENT
    l'enfant du parent (titulaire ou dédié d'une matière), jamais un
    contact ouvert à n'importe quel enseignant de la plateforme."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.academics.models import Child, Enrollment, EnrollmentStatus, Subject
        from apps.users.models import User, UserRole
        from rest_framework.exceptions import PermissionDenied

        if not request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")

        child_id = request.data.get("child_id")
        teacher_id = request.data.get("teacher_id")
        child = get_object_or_404(Child, pk=child_id)

        if not child.parent_id or child.parent.user_id != request.user.id:
            raise PermissionDenied("Cet élève n'est pas rattaché à votre compte.")

        enrollment = Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE).select_related(
            "school_class__homeroom_teacher"
        ).first()
        if not enrollment:
            raise PermissionDenied("Cet élève n'est inscrit dans aucune classe pour l'instant.")

        school_class = enrollment.school_class
        is_homeroom = school_class.homeroom_teacher_id == int(teacher_id) if teacher_id else False
        is_subject_teacher = Subject.objects.filter(school_class=school_class, teacher_id=teacher_id).exists()
        if not (is_homeroom or is_subject_teacher):
            raise PermissionDenied("Cet enseignant n'enseigne pas à cet élève.")

        teacher = get_object_or_404(User, pk=teacher_id)

        from .services import get_or_create_direct_channel

        channel = get_or_create_direct_channel(request.user, teacher)
        return Response(ChannelSerializer(channel, context={"request": request}).data)
