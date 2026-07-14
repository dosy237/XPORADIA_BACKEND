from django.conf import settings
from django.core.mail import send_mail
from django.http import Http404
from django.utils import timezone
from rest_framework import generics, permissions, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import DirectorProfile, User, UserRole

from .models import Department, SchoolClass, Subject, TeacherInvitation, Track
from .serializers import (
    DepartmentSerializer,
    SchoolClassSerializer,
    SubjectSerializer,
    TeacherInvitationPreviewSerializer,
    TrackSerializer,
)


def _require_director(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")


def _director_establishment(user):
    try:
        return user.director_profile
    except DirectorProfile.DoesNotExist:
        raise PermissionDenied("Aucun établissement associé à ce compte.")


class DepartmentViewSet(viewsets.ModelViewSet):
    """CRUD des départements de l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DepartmentSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return Department.objects.filter(establishment__user=self.request.user)

    def perform_create(self, serializer):
        establishment = _director_establishment(self.request.user)
        serializer.save(establishment=establishment)


class TrackViewSet(viewsets.ModelViewSet):
    """CRUD des filières — chaque filière appartient à un département de
    l'établissement du directeur connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TrackSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return Track.objects.filter(department__establishment__user=self.request.user)

    def perform_create(self, serializer):
        department = serializer.validated_data["department"]
        if department.establishment.user_id != self.request.user.id:
            raise PermissionDenied("Ce département n'appartient pas à votre établissement.")
        serializer.save()


class SchoolClassViewSet(viewsets.ModelViewSet):
    """CRUD des classes — chaque classe appartient à une filière de
    l'établissement du directeur connecté, avec affectation de
    l'enseignant titulaire."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SchoolClassSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return SchoolClass.objects.filter(
            track__department__establishment__user=self.request.user
        ).select_related("track", "homeroom_teacher")

    def _validate_track_ownership(self, serializer):
        track = serializer.validated_data.get("track")
        if track and track.department.establishment.user_id != self.request.user.id:
            raise PermissionDenied("Cette filière n'appartient pas à votre établissement.")

    def perform_create(self, serializer):
        self._validate_track_ownership(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._validate_track_ownership(serializer)
        serializer.save()


class MyHomeroomClassesView(generics.ListAPIView):
    """Classes dont l'enseignant connecté est titulaire."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SchoolClassSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return SchoolClass.objects.filter(
            homeroom_teacher=self.request.user, is_active=True
        ).select_related("track", "track__department")


def _get_school_class(class_id):
    try:
        return SchoolClass.objects.select_related(
            "track", "track__department", "homeroom_teacher"
        ).get(id=class_id)
    except SchoolClass.DoesNotExist:
        raise Http404


def _require_homeroom_teacher(school_class, user):
    if school_class.homeroom_teacher_id != user.id:
        raise PermissionDenied("Réservé à l'enseignant titulaire de cette classe.")


def _notify_dedicated_teacher(subject):
    notify_user(
        subject.teacher,
        NotificationType.CLASS_ASSIGNMENT,
        title="Vous avez été affecté(e) à une matière",
        body=(
            f"{subject.school_class.homeroom_teacher.get_full_name()} vous a ajouté(e) comme "
            f"enseignant(e) dédié(e) sur \"{subject.name}\" ({subject.school_class})."
        ),
        data={"subject_id": subject.id, "school_class_id": subject.school_class_id},
    )


def _send_invitation_email(invitation):
    invite_link = f"{settings.INVITE_LINK_BASE}/invite/{invitation.token}"
    send_mail(
        subject=f"Invitation Xporadia — {invitation.subject.name}",
        message=(
            f"{invitation.invited_by.get_full_name()} vous invite à rejoindre Xporadia comme "
            f"enseignant(e) dédié(e) sur \"{invitation.subject.name}\" ({invitation.subject.school_class}).\n\n"
            f"Ouvrez ce lien pour accepter : {invite_link}\n\n"
            "Si vous n'avez pas encore de compte enseignant, ce lien vous permettra d'en créer un."
        ),
        from_email=None,
        recipient_list=[invitation.email],
        fail_silently=True,
    )


def _resolve_teacher_email(subject, email, invited_by):
    """Affecte directement un enseignant existant, ou crée/relance une
    invitation par email s'il n'a pas encore de compte enseignant actif.
    Retourne (résultat, objet) où résultat est "assigned", "invited" ou
    "cleared"."""

    if not email:
        subject.teacher = None
        subject.save(update_fields=["teacher"])
        return "cleared", None

    try:
        user = User.objects.get(email__iexact=email, is_active=True)
    except User.DoesNotExist:
        user = None

    if user and user.has_role(UserRole.TEACHER):
        subject.teacher = user
        subject.save(update_fields=["teacher"])
        return "assigned", user

    invitation, created = TeacherInvitation.objects.get_or_create(
        subject=subject, email=email.lower(), defaults={"invited_by": invited_by}
    )
    if not created and invitation.is_accepted:
        invitation.is_accepted = False
        invitation.accepted_by = None
        invitation.accepted_at = None
        invitation.invited_by = invited_by
        invitation.save(update_fields=["is_accepted", "accepted_by", "accepted_at", "invited_by"])
    _send_invitation_email(invitation)
    return "invited", invitation


class SubjectListCreateView(generics.ListCreateAPIView):
    """Matières d'une classe — créées et gérées par l'enseignant titulaire,
    qui y affecte (ou invite par email) un enseignant dédié."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubjectSerializer
    pagination_class = None

    def get_queryset(self):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_homeroom_teacher(school_class, self.request.user)
        return Subject.objects.filter(school_class=school_class).select_related("teacher")

    def perform_create(self, serializer):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_homeroom_teacher(school_class, self.request.user)
        email = serializer.validated_data.pop("teacher_email", None)
        subject = serializer.save(school_class=school_class)
        if email:
            outcome, _ = _resolve_teacher_email(subject, email, self.request.user)
            if outcome == "assigned":
                _notify_dedicated_teacher(subject)


class SubjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Détail d'une matière — réservé à l'enseignant titulaire de la classe
    à laquelle elle appartient."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubjectSerializer

    def get_queryset(self):
        return Subject.objects.filter(
            school_class__homeroom_teacher=self.request.user
        ).select_related("teacher", "school_class", "school_class__track", "school_class__homeroom_teacher")

    def perform_update(self, serializer):
        email_provided = "teacher_email" in serializer.validated_data
        email = serializer.validated_data.pop("teacher_email", None)
        previous_teacher_id = serializer.instance.teacher_id
        subject = serializer.save()
        if email_provided:
            outcome, _ = _resolve_teacher_email(subject, email, self.request.user)
            if outcome == "assigned" and subject.teacher_id != previous_teacher_id:
                _notify_dedicated_teacher(subject)


class TeacherInvitationPreviewView(generics.RetrieveAPIView):
    """Aperçu public d'une invitation — consultable avant connexion ou
    inscription, pour afficher le contexte (matière, classe, établissement)
    sur l'écran d'acceptation."""

    permission_classes = [permissions.AllowAny]
    serializer_class = TeacherInvitationPreviewSerializer
    lookup_field = "token"
    lookup_url_kwarg = "token"

    def get_queryset(self):
        return TeacherInvitation.objects.filter(is_accepted=False).select_related(
            "subject",
            "subject__school_class",
            "subject__school_class__track",
            "subject__school_class__track__department",
            "subject__school_class__track__department__establishment",
            "invited_by",
        )


class AcceptTeacherInvitationView(APIView):
    """Acceptation d'une invitation — l'enseignant connecté (même adresse
    email que l'invitation) devient l'enseignant dédié de la matière."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token):
        try:
            invitation = TeacherInvitation.objects.select_related(
                "subject", "subject__school_class", "invited_by"
            ).get(token=token, is_accepted=False)
        except TeacherInvitation.DoesNotExist:
            raise Http404

        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        if request.user.email.lower() != invitation.email.lower():
            raise PermissionDenied(f"Cette invitation est destinée à {invitation.email}.")

        subject = invitation.subject
        subject.teacher = request.user
        subject.save(update_fields=["teacher"])

        invitation.is_accepted = True
        invitation.accepted_by = request.user
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["is_accepted", "accepted_by", "accepted_at"])

        notify_user(
            invitation.invited_by,
            NotificationType.CLASS_ASSIGNMENT,
            title="Invitation acceptée",
            body=(
                f"{request.user.get_full_name()} a rejoint \"{subject.name}\" "
                "en tant qu'enseignant(e) dédié(e)."
            ),
            data={"subject_id": subject.id},
        )

        return Response(SubjectSerializer(subject).data)


class MyDedicatedSubjectsView(generics.ListAPIView):
    """Matières où l'enseignant connecté est l'enseignant dédié."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubjectSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return Subject.objects.filter(teacher=self.request.user).select_related(
            "school_class", "school_class__track", "school_class__track__department"
        )
