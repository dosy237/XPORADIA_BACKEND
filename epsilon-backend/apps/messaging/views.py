from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Channel, ChannelMembership, ChannelType, Message
from .realtime import broadcast_to_channel
from .serializers import ChannelSerializer, CreateMessageSerializer, EditMessageSerializer, MessageSerializer
from .services import notify_channel_members, save_uploaded_attachments


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
    # Bug confirmé : la pagination par défaut du projet (20/page, triée du
    # plus ancien au plus récent) renvoyait toujours la PREMIÈRE page à un
    # canal déjà bien rempli. Le frontend n'appelle jamais la page suivante
    # (aucun défilement infini construit) : au-delà de 20 messages, les plus
    # récents devenaient invisibles au destinataire tant qu'il n'ouvrait pas
    # explicitement une page 2 inexistante côté UI. Désactivée ici comme
    # pour les autres listes non bornées du projet (ex. bibliothèque).
    pagination_class = None

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
        attachments = save_uploaded_attachments(self.request.FILES.getlist("attachments"), self.request)
        message = serializer.save(channel=channel, author=self.request.user, attachments=attachments)
        notify_channel_members(channel, message, self.request)
        broadcast_to_channel(
            channel.id, "message_created",
            {"message": MessageSerializer(message, context={"request": self.request}).data},
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


class ContactClassmateView(APIView):
    """Ouvre (ou retrouve) une conversation directe entre deux élèves de la
    même classe active — le point d'entrée depuis la liste de camarades de
    « Ma classe » ; le mécanisme de canal direct lui-même est celui,
    déjà existant, partagé avec toute la messagerie (aucun nouveau
    mécanisme de canal)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.academics.models import Child, Enrollment, EnrollmentStatus
        from rest_framework.exceptions import PermissionDenied

        from .services import get_or_create_direct_channel

        requester_child = getattr(request.user, "child_profile", None)
        if not requester_child:
            raise PermissionDenied("Réservé aux comptes élève.")

        classmate_id = request.data.get("classmate_id")
        classmate = get_object_or_404(Child, pk=classmate_id)
        if classmate.id == requester_child.id:
            raise PermissionDenied("Vous ne pouvez pas vous contacter vous-même.")
        if not classmate.user_id:
            raise PermissionDenied("Cet élève n'a pas encore activé son compte.")

        requester_class = Enrollment.objects.filter(
            child=requester_child, status=EnrollmentStatus.ACTIVE
        ).values_list("school_class_id", flat=True).first()
        classmate_class = Enrollment.objects.filter(
            child=classmate, status=EnrollmentStatus.ACTIVE
        ).values_list("school_class_id", flat=True).first()
        if not requester_class or requester_class != classmate_class:
            raise PermissionDenied("Cet élève n'est pas dans votre classe.")

        channel = get_or_create_direct_channel(request.user, classmate.user)
        return Response(ChannelSerializer(channel, context={"request": request}).data)


class PublishExerciseView(APIView):
    """Publication d'un devoir/examen directement depuis le canal de
    matière — l'action « Ajouter un devoir » du menu « + », réservée à
    l'enseignant dédié de cette matière (seul membre enseignant du canal).
    Un devoir vit toujours dans le canal de matière, jamais dans le canal
    de classe (voir apps.messaging.models, docstring de Channel)."""

    permission_classes = [permissions.IsAuthenticated, IsVerifiedToMessage]

    def post(self, request, channel_id):
        from django.utils.dateparse import parse_datetime
        from rest_framework.exceptions import PermissionDenied, ValidationError

        from apps.virtual_classes.models import Exercise, ExerciseKind, ExerciseStatus, VirtualClass
        from apps.virtual_classes.services import notify_enrolled_parents
        from apps.notifications.models import NotificationType

        channel = get_object_or_404(Channel, pk=channel_id)
        if channel.channel_type != ChannelType.SUBJECT:
            raise PermissionDenied("Un devoir ne peut être publié que dans un canal de matière.")
        subject = channel.subject
        if subject.teacher_id != request.user.id:
            raise PermissionDenied("Réservé à l'enseignant dédié de cette matière.")

        title = (request.data.get("title") or "").strip()
        instructions = (request.data.get("instructions") or "").strip()
        kind = request.data.get("kind", ExerciseKind.HOMEWORK)
        attachments = save_uploaded_attachments(request.FILES.getlist("attachments"), request)
        deadline_raw = request.data.get("deadline")

        if not title or not instructions:
            raise ValidationError("Titre et consignes sont obligatoires.")
        if kind not in ExerciseKind.values:
            raise ValidationError("Type de devoir invalide.")
        deadline = parse_datetime(deadline_raw) if deadline_raw else None
        if not deadline:
            raise ValidationError("La date limite est obligatoire.")

        virtual_class, _ = VirtualClass.objects.get_or_create(subject=subject)
        exercise = Exercise.objects.create(
            virtual_class=virtual_class, kind=kind, title=title, instructions=instructions,
            attachments=attachments, deadline=deadline,
            status=ExerciseStatus.PUBLISHED, published_at=timezone.now(),
        )

        message = Message.objects.create(channel=channel, author=request.user, exercise_id=exercise.id)
        notify_channel_members(
            channel, message, request, preview_override=f"Nouveau devoir : {title}"
        )
        notify_enrolled_parents(
            subject.school_class, NotificationType.EXERCISE_PUBLISHED,
            title="Nouveau devoir publié",
            body=f"« {title} » a été publié pour la matière {subject.name}.",
        )
        broadcast_to_channel(
            channel.id, "message_created",
            {"message": MessageSerializer(message, context={"request": request}).data},
        )
        return Response(
            MessageSerializer(message, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


class SubmitExerciseMessageView(APIView):
    """Soumission d'un devoir depuis le fil privé élève/enseignant — crée
    ou met à jour la Submission de l'élève (jamais un doublon, voir
    unique_together sur Submission) et publie le message correspondant
    dans cette même DM, avec exercise_id renseigné pour rester traçable
    dans un historique qui mélange discussion normale et soumissions de
    plusieurs devoirs différents."""

    permission_classes = [permissions.IsAuthenticated, IsVerifiedToMessage]

    def post(self, request, channel_id):
        from rest_framework.exceptions import PermissionDenied, ValidationError

        from apps.academics.models import Enrollment, EnrollmentStatus
        from apps.notifications.models import NotificationType
        from apps.notifications.services import notify_user
        from apps.virtual_classes.models import Exercise, ExerciseStatus, Submission, SubmissionStatus

        channel = get_object_or_404(Channel, pk=channel_id)
        if channel.channel_type != ChannelType.DIRECT:
            raise PermissionDenied("La soumission d'un devoir se fait dans le fil privé avec l'enseignant.")
        _require_membership(channel, request.user)

        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")

        exercise_id = request.data.get("exercise_id")
        exercise = get_object_or_404(
            Exercise.objects.select_related("virtual_class__subject__school_class"), pk=exercise_id
        )
        subject = exercise.virtual_class.subject

        other_member = channel.memberships.exclude(user=request.user).select_related("user").first()
        if not other_member or other_member.user_id != subject.teacher_id:
            raise PermissionDenied("Ce devoir n'appartient pas à l'enseignant de cette conversation.")
        if exercise.status != ExerciseStatus.PUBLISHED:
            raise PermissionDenied("Ce devoir n'accepte plus de nouvelle soumission.")
        is_enrolled = Enrollment.objects.filter(
            child=child, school_class=subject.school_class, status=EnrollmentStatus.ACTIVE
        ).exists()
        if not is_enrolled:
            raise PermissionDenied("Vous n'êtes pas inscrit(e) dans la classe de ce devoir.")

        content = (request.data.get("content") or "").strip()
        attachments = save_uploaded_attachments(request.FILES.getlist("attachments"), request)
        if not content and not attachments:
            raise ValidationError("Ajoutez un texte ou une pièce jointe.")

        Submission.objects.update_or_create(
            exercise=exercise, child=child,
            defaults={
                "content": content, "attachments": attachments,
                "status": SubmissionStatus.SUBMITTED, "submitted_by": request.user,
            },
        )

        message = Message.objects.create(
            channel=channel, author=request.user, body=content, attachments=attachments,
            exercise_id=exercise.id,
        )
        if subject.teacher:
            notify_user(
                subject.teacher, NotificationType.EXERCISE_SUBMITTED,
                title="Nouvelle copie soumise",
                body=f"{child.first_name} a soumis une copie pour « {exercise.title} ».",
            )
        broadcast_to_channel(
            channel.id, "message_created",
            {"message": MessageSerializer(message, context={"request": request}).data},
        )
        return Response(
            MessageSerializer(message, context={"request": request}).data, status=status.HTTP_201_CREATED
        )
