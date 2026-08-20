import re
import unicodedata

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import Child, DirectorProfile, ParentProfile, User, UserRole

from .models import (
    DelegatedTask,
    Department,
    Enrollment,
    EnrollmentStatus,
    SchoolClass,
    Subject,
    TaskDelegation,
    TeacherInvitation,
    TimetableSlot,
    Track,
)
from .serializers import (
    ChildBasicSerializer,
    DepartmentSerializer,
    EnrollmentSerializer,
    SchoolClassSerializer,
    SubjectSerializer,
    TeacherInvitationPreviewSerializer,
    TimetableSlotSerializer,
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
    """CRUD des départements de l'établissement du directeur connecté —
    jamais délégable, contrairement aux filières et classes en dessous."""

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
    l'établissement du directeur connecté. La création peut être déléguée
    par le directeur à un enseignant précis pour un département donné
    (Department.track_delegates) — la lecture reste director-only pour ne
    pas exposer toute la structure académique à un enseignant délégué sur
    un seul département."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TrackSerializer
    pagination_class = None

    def get_queryset(self):
        _require_director(self.request.user)
        return Track.objects.filter(department__establishment__user=self.request.user)

    def perform_create(self, serializer):
        department = serializer.validated_data["department"]
        user = self.request.user
        is_owner = department.establishment.user_id == user.id
        is_delegate = department.track_delegates.filter(id=user.id).exists()
        if not (is_owner or is_delegate):
            raise PermissionDenied(
                "Ce département n'appartient pas à votre établissement, et vous n'êtes pas "
                "délégué pour y créer des filières."
            )
        serializer.save()


class MyDelegationsView(APIView):
    """Ce que l'enseignant connecté est autorisé à faire par délégation —
    création de filière/classe (structure académique), et tâches
    établissement (comme la gestion des emplois du temps)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        departments = Department.objects.filter(track_delegates=request.user).select_related("establishment")
        tracks = Track.objects.filter(class_delegates=request.user).select_related(
            "department__establishment"
        )
        tasks = TaskDelegation.objects.filter(teacher=request.user).select_related("establishment")
        return Response({
            "departments_for_tracks": DepartmentSerializer(departments, many=True).data,
            "tracks_for_classes": TrackSerializer(tracks, many=True).data,
            "tasks": [
                {"task": t.task, "task_label": t.get_task_display(), "establishment_name": t.establishment.school_name}
                for t in tasks
            ],
        })


class TaskDelegationsView(APIView):
    """Gestion des délégations de tâches établissement — réservée au
    directeur. Contrairement aux délégations de filière/classe (scopées à
    un objet précis), celles-ci portent sur TOUT l'établissement."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        _require_director(request.user)
        establishment = _director_establishment(request.user)
        delegations = TaskDelegation.objects.filter(establishment=establishment).select_related("teacher")
        return Response([
            {
                "id": d.id, "task": d.task, "task_label": d.get_task_display(),
                "teacher": {
                    "id": d.teacher.id, "first_name": d.teacher.first_name,
                    "last_name": d.teacher.last_name, "email": d.teacher.email,
                    "avatar": request.build_absolute_uri(d.teacher.avatar.url) if d.teacher.avatar else None,
                },
            }
            for d in delegations
        ])

    def post(self, request):
        _require_director(request.user)
        establishment = _director_establishment(request.user)
        task = request.data.get("task")
        email = request.data.get("email", "").strip().lower()
        if task not in DelegatedTask.values:
            raise ValidationError({"task": "Tâche inconnue."})
        try:
            teacher = User.objects.get(email=email, primary_role=UserRole.TEACHER, is_active=True)
        except User.DoesNotExist:
            raise ValidationError({"email": "Aucun enseignant actif ne correspond à cet email."})
        delegation, created = TaskDelegation.objects.get_or_create(
            establishment=establishment, teacher=teacher, task=task
        )
        if created:
            notify_user(
                teacher, NotificationType.CLASS_ASSIGNMENT,
                title="Délégation reçue",
                body=f"{establishment.school_name} vous a confié : {delegation.get_task_display()}.",
            )
        return Response({"id": delegation.id, "task": delegation.task}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        _require_director(request.user)
        establishment = _director_establishment(request.user)
        task = request.data.get("task")
        email = request.data.get("email", "").strip().lower()
        TaskDelegation.objects.filter(
            establishment=establishment, task=task, teacher__email=email
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyTimetableDelegationClassesView(generics.ListAPIView):
    """Classes accessibles à l'enseignant connecté au titre de sa
    délégation "gestion des emplois du temps" — il n'est pas
    nécessairement titulaire d'aucune d'entre elles, d'où ce point d'accès
    dédié pour naviguer jusqu'à l'éditeur d'emploi du temps de chacune."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SchoolClassSerializer
    pagination_class = None

    def get_queryset(self):
        establishments = DirectorProfile.objects.filter(
            task_delegations__teacher=self.request.user, task_delegations__task=DelegatedTask.TIMETABLE
        )
        return SchoolClass.objects.filter(
            track__department__establishment__in=establishments
        ).select_related("track", "homeroom_teacher")


class DepartmentDelegatesView(APIView):
    """Gestion des enseignants délégués pour créer des filières dans ce
    département — réservée au directeur, jamais à un délégué lui-même
    (pas de délégation en cascade)."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_department(self, department_id, user):
        department = get_object_or_404(Department, pk=department_id)
        if department.establishment.user_id != user.id:
            raise PermissionDenied("Ce département n'appartient pas à votre établissement.")
        return department

    def post(self, request, department_id):
        department = self._get_department(department_id, request.user)
        email = request.data.get("email", "").strip().lower()
        try:
            teacher = User.objects.get(email=email, primary_role=UserRole.TEACHER, is_active=True)
        except User.DoesNotExist:
            raise ValidationError({"email": "Aucun enseignant actif ne correspond à cet email."})
        department.track_delegates.add(teacher)
        notify_user(
            teacher, NotificationType.CLASS_ASSIGNMENT,
            title="Délégation reçue",
            body=f"Vous pouvez désormais créer des filières dans le département « {department.name} ».",
        )
        return Response(DepartmentSerializer(department).data)

    def delete(self, request, department_id):
        department = self._get_department(department_id, request.user)
        email = request.data.get("email", "").strip().lower()
        department.track_delegates.filter(email=email).delete()
        return Response(DepartmentSerializer(department).data)


class TrackDelegatesView(APIView):
    """Symétrique à DepartmentDelegatesView, un niveau plus bas — délègue
    la création des classes d'une filière."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_track(self, track_id, user):
        track = get_object_or_404(Track, pk=track_id)
        if track.department.establishment.user_id != user.id:
            raise PermissionDenied("Cette filière n'appartient pas à votre établissement.")
        return track

    def post(self, request, track_id):
        track = self._get_track(track_id, request.user)
        email = request.data.get("email", "").strip().lower()
        try:
            teacher = User.objects.get(email=email, primary_role=UserRole.TEACHER, is_active=True)
        except User.DoesNotExist:
            raise ValidationError({"email": "Aucun enseignant actif ne correspond à cet email."})
        track.class_delegates.add(teacher)
        notify_user(
            teacher, NotificationType.CLASS_ASSIGNMENT,
            title="Délégation reçue",
            body=f"Vous pouvez désormais créer des classes dans la filière « {track.name} ».",
        )
        return Response(TrackSerializer(track).data)

    def delete(self, request, track_id):
        track = self._get_track(track_id, request.user)
        email = request.data.get("email", "").strip().lower()
        track.class_delegates.filter(email=email).delete()
        return Response(TrackSerializer(track).data)


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
        if not track:
            return
        user = self.request.user
        is_owner = track.department.establishment.user_id == user.id
        is_delegate = track.class_delegates.filter(id=user.id).exists()
        if not (is_owner or is_delegate):
            raise PermissionDenied(
                "Cette filière n'appartient pas à votre établissement, et vous n'êtes pas "
                "délégué pour y créer des classes."
            )

    def perform_create(self, serializer):
        self._validate_track_ownership(serializer)
        school_class = serializer.save()
        if school_class.homeroom_teacher_id:
            self._notify_and_grant_homeroom(school_class, previous_teacher_id=None)

    def perform_update(self, serializer):
        self._validate_track_ownership(serializer)
        previous_teacher_id = serializer.instance.homeroom_teacher_id
        school_class = serializer.save()
        if school_class.homeroom_teacher_id != previous_teacher_id:
            self._notify_and_grant_homeroom(school_class, previous_teacher_id)

    def _notify_and_grant_homeroom(self, school_class, previous_teacher_id):
        """Nomination (ou changement) de titulaire — notifie le nouveau
        titulaire et transfère les droits d'administration du canal de
        classe, qui ne se mettent jamais à jour tout seuls sinon (le
        titulaire précédent resterait admin indéfiniment)."""
        from apps.messaging.models import ChannelMembership
        from apps.messaging.services import get_or_create_class_channel

        if previous_teacher_id:
            ChannelMembership.objects.filter(
                channel__school_class=school_class, user_id=previous_teacher_id
            ).update(is_admin=False)

        new_teacher = school_class.homeroom_teacher
        if new_teacher:
            channel = get_or_create_class_channel(school_class)
            ChannelMembership.objects.update_or_create(
                channel=channel, user=new_teacher, defaults={"is_admin": True}
            )
            notify_user(
                new_teacher,
                NotificationType.CLASS_ASSIGNMENT,
                title="Nomination professeur principal",
                body=f"Vous avez été nommé(e) professeur principal de la classe {school_class}.",
            )


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
            "track", "track__department", "track__department__establishment", "homeroom_teacher"
        ).get(id=class_id)
    except SchoolClass.DoesNotExist:
        raise Http404


def _require_homeroom_teacher(school_class, user):
    if school_class.homeroom_teacher_id != user.id:
        raise PermissionDenied("Réservé à l'enseignant titulaire de cette classe.")


def _require_roster_access(school_class, user):
    """Le titulaire de la classe et le directeur de l'établissement peuvent
    consulter/alimenter le registre au quotidien (nouvelle inscription).
    Volontairement distinct de _require_timetable_write_access ci-dessous
    : un enseignant délégué pour les emplois du temps ne doit JAMAIS
    pouvoir toucher aux effectifs."""
    if school_class.homeroom_teacher_id == user.id:
        return
    if user.has_role(UserRole.DIRECTOR) and school_class.track.department.establishment.user_id == user.id:
        return
    raise PermissionDenied("Réservé au titulaire de cette classe ou au directeur de l'établissement.")


def _require_timetable_write_access(school_class, user):
    """Titulaire de la classe, directeur, OU enseignant délégué par le
    directeur pour la gestion des emplois du temps de TOUT l'établissement
    (DelegatedTask.TIMETABLE — le \"censeur\", souvent lui-même enseignant,
    qui gère les emplois du temps de toute l'école sans être titulaire de
    chaque classe). Ne donne accès qu'à l'emploi du temps, jamais aux
    effectifs — voir _require_roster_access, volontairement séparée."""
    if school_class.homeroom_teacher_id == user.id:
        return
    establishment = school_class.track.department.establishment
    if user.has_role(UserRole.DIRECTOR) and establishment.user_id == user.id:
        return
    if TaskDelegation.objects.filter(
        establishment=establishment, teacher=user, task=DelegatedTask.TIMETABLE
    ).exists():
        return
    raise PermissionDenied(
        "Réservé au titulaire de cette classe, au directeur de l'établissement, ou à un enseignant "
        "délégué pour la gestion des emplois du temps."
    )


def _require_establishment_director(school_class, user):
    """Le passage/redoublement/départ franchit la frontière d'une classe —
    seul le directeur, qui a autorité sur toute la structure académique de
    l'établissement, peut décider de la classe cible."""
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé au directeur de l'établissement.")
    if school_class.track.department.establishment.user_id != user.id:
        raise PermissionDenied("Cette classe n'appartient pas à votre établissement.")


def _notify_parent_of_enrollment_change(enrollment, title, body):
    if not enrollment.child.parent_id:
        return  # élève auto-inscrit sans parent rattaché — rien à notifier de ce côté
    notify_user(
        enrollment.child.parent.user,
        NotificationType.ENROLLMENT_UPDATE,
        title=title,
        body=body,
        data={"child_id": enrollment.child_id, "school_class_id": enrollment.school_class_id},
    )


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
        from apps.messaging.services import ensure_teacher_dm_channels

        ensure_teacher_dm_channels(subject)
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
        _require_class_member_access(school_class, self.request.user)
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


class SubjectCoefficientView(APIView):
    """Modification du coefficient d'une matière — strictement réservée au
    directeur (jamais l'enseignant titulaire ni l'enseignant dédié, qui ne
    doivent pas pouvoir peser sur l'importance de leur propre matière dans
    la moyenne générale). Volontairement séparée de SubjectDetailView."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, subject_id):
        subject = get_object_or_404(
            Subject.objects.select_related("school_class__track__department__establishment"), pk=subject_id
        )
        if subject.school_class.track.department.establishment.user_id != request.user.id:
            raise PermissionDenied("Cette matière n'appartient pas à votre établissement.")
        coefficient = request.data.get("coefficient")
        try:
            coefficient = int(coefficient)
            if coefficient < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError({"coefficient": "Doit être un entier positif."})
        subject.coefficient = coefficient
        subject.save(update_fields=["coefficient"])
        return Response(SubjectSerializer(subject).data)


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
        from apps.messaging.services import ensure_teacher_dm_channels

        ensure_teacher_dm_channels(subject)

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


class ChildLookupView(generics.ListAPIView):
    """Recherche des enfants pour inscription en classe — par email du
    parent (élève ajouté par sa famille), ou par email de l'élève
    lui-même s'il s'est auto-inscrit (Child.parent est alors nul, aucun
    parent à chercher)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChildBasicSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if not (user.has_role(UserRole.TEACHER) or user.has_role(UserRole.DIRECTOR)):
            raise PermissionDenied("Réservé aux enseignants et directeurs.")

        child_email = self.request.query_params.get("child_email")
        if child_email:
            return Child.objects.filter(user__email__iexact=child_email)

        parent_email = self.request.query_params.get("parent_email")
        if parent_email:
            try:
                parent = ParentProfile.objects.get(user__email__iexact=parent_email)
            except ParentProfile.DoesNotExist:
                return Child.objects.none()
            return parent.children.all()

        return Child.objects.none()


class ClassRosterView(generics.ListCreateAPIView):
    """Élèves activement inscrits dans une classe — consultable par le
    titulaire et le directeur, alimentable par les deux (nouvelle
    inscription en cours d'année)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EnrollmentSerializer
    pagination_class = None

    def get_school_class(self):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_roster_access(school_class, self.request.user)
        return school_class

    def get_queryset(self):
        school_class = self.get_school_class()
        return Enrollment.objects.filter(
            school_class=school_class, status=EnrollmentStatus.ACTIVE
        ).select_related("child")

    def create(self, request, *args, **kwargs):
        school_class = self.get_school_class()
        child_id = request.data.get("child_id")
        if not child_id:
            raise ValidationError({"child_id": "Ce champ est requis."})
        try:
            child = Child.objects.select_related("parent__user").get(id=child_id)
        except Child.DoesNotExist:
            raise ValidationError({"child_id": "Élève introuvable."})

        enrollment, created = Enrollment.objects.get_or_create(
            child=child, school_class=school_class, defaults={"status": EnrollmentStatus.ACTIVE}
        )
        if not created and enrollment.status != EnrollmentStatus.ACTIVE:
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.ended_at = None
            enrollment.save(update_fields=["status", "ended_at"])
        if created:
            _notify_parent_of_enrollment_change(
                enrollment,
                title="Inscription confirmée",
                body=f"{child.first_name} est désormais inscrit(e) en {school_class}.",
            )

        serializer = self.get_serializer(enrollment)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)


class RemoveStudentFromEstablishmentView(APIView):
    """Retrait d'un élève de l'établissement ENTIER — clôture toutes ses
    inscriptions actives, quelle que soit la classe. Même geste unique,
    portée plus large."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, child_id):
        establishment = _director_establishment(request.user)
        enrollments = Enrollment.objects.filter(
            child_id=child_id, status=EnrollmentStatus.ACTIVE,
            school_class__track__department__establishment=establishment,
        )
        if not enrollments.exists():
            raise Http404
        for enrollment in enrollments:
            enrollment.status = EnrollmentStatus.WITHDRAWN
            enrollment.ended_at = timezone.now()
            enrollment.save(update_fields=["status", "ended_at"])
            _notify_parent_of_enrollment_change(
                enrollment, title="Retrait de l'établissement",
                body=f"{enrollment.child.first_name} n'est plus inscrit(e) à {establishment.school_name}.",
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


_TRANSITION_MESSAGES = {
    EnrollmentStatus.PROMOTED: "est passé(e) en classe supérieure",
    EnrollmentStatus.REPEATING: "redouble",
    EnrollmentStatus.WITHDRAWN: "a quitté l'établissement",
}


class YearEndReadinessView(generics.ListAPIView):
    """Suivi de fin d'année pour le directeur — quelles classes ont
    terminé leurs décisions de passage (effectif actif retombé à zéro,
    chaque élève ayant reçu une décision), lesquelles restent en attente.
    Aucun nouveau modèle : déduit directement des inscriptions actives
    restantes, donc toujours exact, jamais désynchronisé."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        establishment = _director_establishment(request.user)
        classes = SchoolClass.objects.filter(
            track__department__establishment=establishment, is_active=True
        ).select_related("homeroom_teacher")

        overview = []
        for school_class in classes:
            remaining = Enrollment.objects.filter(
                school_class=school_class, status=EnrollmentStatus.ACTIVE
            ).count()
            overview.append({
                "school_class": school_class.id,
                "name": school_class.name,
                "school_year": school_class.school_year,
                "homeroom_teacher": (
                    f"{school_class.homeroom_teacher.first_name} {school_class.homeroom_teacher.last_name}"
                    if school_class.homeroom_teacher else None
                ),
                "students_remaining": remaining,
                "is_complete": remaining == 0,
            })
        return Response(overview)


class BatchRosterTransitionView(APIView):
    """Passage de fin d'année EN MASSE — le titulaire traite tout son
    effectif en un seul geste plutôt qu'élève par élève : une classe
    cible par défaut pour le groupe qui passe, les exceptions
    (redoublement, départ) précisées une par une seulement quand
    nécessaire. Un échec sur une ligne n'annule jamais les autres —
    rapport détaillé renvoyé, comme pour l'admission en masse."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, class_id):
        school_class = _get_school_class(class_id)
        _require_roster_access(school_class, request.user)

        default_target_class_id = request.data.get("default_target_class_id")
        entries = request.data.get("entries", [])
        if not isinstance(entries, list) or not entries:
            raise ValidationError({"entries": "Au moins une entrée est requise."})

        results = []
        for entry in entries:
            child_id = entry.get("child_id")
            new_status = entry.get("status")
            try:
                if new_status not in (EnrollmentStatus.PROMOTED, EnrollmentStatus.REPEATING, EnrollmentStatus.WITHDRAWN):
                    raise ValueError("Statut invalide.")
                enrollment = Enrollment.objects.select_related("child", "school_class").get(
                    school_class=school_class, child_id=child_id, status=EnrollmentStatus.ACTIVE
                )
                enrollment.status = new_status
                enrollment.ended_at = timezone.now()
                enrollment.save(update_fields=["status", "ended_at"])

                new_enrollment = None
                if new_status in (EnrollmentStatus.PROMOTED, EnrollmentStatus.REPEATING):
                    target_class_id = entry.get("target_class_id") or default_target_class_id
                    if not target_class_id:
                        raise ValueError("Aucune classe cible (ni par ligne, ni par défaut).")
                    target_class = _get_school_class(target_class_id)
                    if (
                        target_class.track.department.establishment_id
                        != school_class.track.department.establishment_id
                    ):
                        raise ValueError("La classe cible doit appartenir à votre établissement.")
                    new_enrollment, _ = Enrollment.objects.get_or_create(
                        child=enrollment.child, school_class=target_class,
                        defaults={"status": EnrollmentStatus.ACTIVE},
                    )

                _notify_parent_of_enrollment_change(
                    enrollment, title="Mise à jour de scolarité",
                    body=(
                        f"{enrollment.child.first_name} {_TRANSITION_MESSAGES[new_status]}"
                        + (f" ({new_enrollment.school_class})." if new_enrollment else ".")
                    ),
                )
                results.append({"child_id": child_id, "success": True})
            except (Enrollment.DoesNotExist, ValueError, Http404) as exc:
                results.append({"child_id": child_id, "success": False, "error": str(exc)})

        return Response({
            "processed": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "results": results,
        })



class RosterEnrollmentTransitionView(APIView):
    """Clôt une inscription (passage, redoublement, départ) — réservé au
    directeur car l'opération peut ouvrir une nouvelle inscription dans
    une classe différente, dont le titulaire n'est pas forcément le même."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            enrollment = Enrollment.objects.select_related(
                "school_class", "school_class__track", "school_class__track__department",
                "school_class__track__department__establishment", "child", "child__parent__user",
            ).get(pk=pk)
        except Enrollment.DoesNotExist:
            raise Http404

        new_status = request.data.get("status")
        if new_status not in (EnrollmentStatus.PROMOTED, EnrollmentStatus.REPEATING, EnrollmentStatus.WITHDRAWN):
            raise ValidationError({"status": "Statut invalide."})

        if new_status == EnrollmentStatus.WITHDRAWN:
            # Un simple retrait, sans classe cible à choisir ailleurs dans
            # l'établissement — délégable au titulaire, comme le reste de
            # la gestion des effectifs.
            _require_roster_access(enrollment.school_class, request.user)
        else:
            # Passage/redoublement — validé par le professeur principal
            # pour SES propres élèves (comme dans un établissement réel),
            # ou le directeur. La classe cible doit simplement appartenir
            # au même établissement, vérifié plus bas.
            _require_roster_access(enrollment.school_class, request.user)

        enrollment.status = new_status
        enrollment.ended_at = timezone.now()
        enrollment.save(update_fields=["status", "ended_at"])

        new_enrollment = None
        if new_status in (EnrollmentStatus.PROMOTED, EnrollmentStatus.REPEATING):
            target_class_id = request.data.get("target_class_id")
            if not target_class_id:
                raise ValidationError({"target_class_id": "Ce champ est requis pour ce statut."})
            target_class = _get_school_class(target_class_id)
            if target_class.track.department.establishment_id != enrollment.school_class.track.department.establishment_id:
                raise PermissionDenied("La classe cible doit appartenir à votre établissement.")
            new_enrollment, _ = Enrollment.objects.get_or_create(
                child=enrollment.child, school_class=target_class,
                defaults={"status": EnrollmentStatus.ACTIVE},
            )

        _notify_parent_of_enrollment_change(
            enrollment,
            title="Mise à jour de scolarité",
            body=(
                f"{enrollment.child.first_name} {_TRANSITION_MESSAGES[new_status]}"
                + (f" ({new_enrollment.school_class})." if new_enrollment else ".")
            ),
        )

        return Response(
            {
                "closed": EnrollmentSerializer(enrollment).data,
                "new_enrollment": EnrollmentSerializer(new_enrollment).data if new_enrollment else None,
            }
        )


def _require_class_member_access(school_class, user):
    """Lecture de l'emploi du temps — titulaire, directeur, enseignant
    dédié d'une matière de la classe, élève/parent qui y est inscrit, ou
    enseignant délégué pour la gestion des emplois du temps de tout
    l'établissement (voir TaskDelegation)."""
    if school_class.homeroom_teacher_id == user.id:
        return
    establishment = school_class.track.department.establishment
    if user.has_role(UserRole.DIRECTOR) and establishment.user_id == user.id:
        return
    if Subject.objects.filter(school_class=school_class, teacher_id=user.id).exists():
        return
    if TaskDelegation.objects.filter(
        establishment=establishment, teacher=user, task=DelegatedTask.TIMETABLE
    ).exists():
        return
    child = getattr(user, "child_profile", None)
    if child and Enrollment.objects.filter(
        child=child, school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).exists():
        return
    if Enrollment.objects.filter(
        child__parent__user=user, school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).exists():
        return
    raise PermissionDenied("Vous n'avez pas accès à l'emploi du temps de cette classe.")


class TimetableView(generics.ListCreateAPIView):
    """Emploi du temps d'une classe — modifié par le titulaire, le
    directeur, ou un enseignant délégué pour la gestion des emplois du
    temps de l'établissement ; consultable par tous ceux qui appartiennent
    à la classe (élèves, parents, enseignants dédiés)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TimetableSlotSerializer
    pagination_class = None

    def get_queryset(self):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_class_member_access(school_class, self.request.user)
        return TimetableSlot.objects.filter(school_class=school_class).select_related("subject")

    def perform_create(self, serializer):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_timetable_write_access(school_class, self.request.user)
        subject = serializer.validated_data["subject"]
        if subject.school_class_id != school_class.id:
            raise ValidationError({"subject": "Cette matière n'appartient pas à cette classe."})
        serializer.save(school_class=school_class)


class TimetableSlotDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TimetableSlotSerializer

    def get_queryset(self):
        return TimetableSlot.objects.select_related("school_class__track__department__establishment", "subject")

    def get_object(self):
        slot = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        _require_class_member_access(slot.school_class, self.request.user)
        return slot

    def perform_update(self, serializer):
        slot = serializer.instance
        _require_timetable_write_access(slot.school_class, self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        _require_timetable_write_access(instance.school_class, self.request.user)
        instance.delete()


class MyTimetableView(generics.ListAPIView):
    """Emploi du temps de l'élève connecté — résout sa classe active
    automatiquement, cohérent avec my-subjects/my-submissions côté
    virtual_classes (pas besoin que le frontend connaisse l'ID de classe)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TimetableSlotSerializer
    pagination_class = None

    def get_queryset(self):
        child = getattr(self.request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        enrollment = Enrollment.objects.filter(
            child=child, status=EnrollmentStatus.ACTIVE
        ).select_related("school_class").first()
        if not enrollment:
            return TimetableSlot.objects.none()
        return TimetableSlot.objects.filter(school_class=enrollment.school_class).select_related("subject")


class MyClassView(APIView):
    """Vue \"Ma classe\" côté élève — titulaire + liste des camarades,
    volontairement limitée au prénom/nom (pas de fiche détaillée entre
    élèves, cohérent avec l'absence de tout élève dans l'Annuaire public)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        enrollment = (
            Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
            .select_related("school_class__homeroom_teacher")
            .first()
        )
        if not enrollment:
            return Response({
                "school_class_name": None, "homeroom_teacher": None, "classmates": [],
                "establishment_name": None, "class_level": child.class_level, "status": None,
                "birth_date": child.birth_date,
            })

        school_class = enrollment.school_class
        classmates = (
            Enrollment.objects.filter(school_class=school_class, status=EnrollmentStatus.ACTIVE)
            .exclude(child=child)
            .select_related("child")
            .order_by("child__first_name")
        )
        teacher = school_class.homeroom_teacher
        return Response(
            {
                "school_class_name": str(school_class),
                "homeroom_teacher": (
                    {
                        "first_name": teacher.first_name, "last_name": teacher.last_name,
                        "avatar": request.build_absolute_uri(teacher.avatar.url) if teacher.avatar else None,
                    }
                    if teacher else None
                ),
                "classmates": [
                    {"id": e.child.id, "first_name": e.child.first_name, "last_name": e.child.last_name}
                    for e in classmates
                ],
                "establishment_name": school_class.track.department.establishment.school_name,
                "class_level": child.class_level,
                "status": enrollment.status,
                "birth_date": child.birth_date,
            }
        )


def _require_child_belongs_to_parent(child_id, user):
    """Vérifie que l'enfant appartient bien au parent connecté — jamais
    d'accès à la fiche d'un enfant qui n'est pas le sien."""
    if not user.has_role(UserRole.PARENT):
        raise PermissionDenied("Réservé aux parents.")
    child = get_object_or_404(Child, pk=child_id)
    if not child.parent_id or child.parent.user_id != user.id:
        raise PermissionDenied("Cet élève n'est pas rattaché à votre compte.")
    return child


class ChildClassView(APIView):
    """Vue "Sa classe" côté PARENT — même contenu que MyClassView côté
    élève, complété par la liste des enseignants (titulaire + dédiés de
    chaque matière) pour pouvoir les contacter directement."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, child_id):
        child = _require_child_belongs_to_parent(child_id, request.user)
        enrollment = (
            Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE)
            .select_related("school_class__homeroom_teacher")
            .first()
        )
        if not enrollment:
            return Response({"school_class_name": None, "homeroom_teacher": None, "teachers": []})

        school_class = enrollment.school_class
        teacher = school_class.homeroom_teacher

        def _avatar_url(user):
            return request.build_absolute_uri(user.avatar.url) if user.avatar else None

        teachers = []
        if teacher:
            teachers.append({
                "id": teacher.id, "first_name": teacher.first_name, "last_name": teacher.last_name,
                "avatar": _avatar_url(teacher), "role_label": "Titulaire",
            })
        for subject in Subject.objects.filter(school_class=school_class, teacher__isnull=False).select_related("teacher"):
            if subject.teacher_id == (teacher.id if teacher else None):
                continue  # déjà listé comme titulaire, pas de doublon
            teachers.append({
                "id": subject.teacher.id, "first_name": subject.teacher.first_name,
                "last_name": subject.teacher.last_name, "avatar": _avatar_url(subject.teacher),
                "role_label": subject.name,
            })

        return Response({
            "school_class_name": str(school_class),
            "homeroom_teacher": (
                {"first_name": teacher.first_name, "last_name": teacher.last_name, "avatar": _avatar_url(teacher)}
                if teacher else None
            ),
            "teachers": teachers,
        })


class ChildTimetableView(generics.ListAPIView):
    """Emploi du temps d'un enfant, côté parent — lecture seule."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TimetableSlotSerializer
    pagination_class = None

    def get_queryset(self):
        child = _require_child_belongs_to_parent(self.kwargs["child_id"], self.request.user)
        enrollment = Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE).first()
        if not enrollment:
            return TimetableSlot.objects.none()
        return TimetableSlot.objects.filter(school_class=enrollment.school_class).select_related("subject")


def _normalize_for_level_match(text: str) -> str:
    """Retire les accents, met en minuscule — pour comparer "5ème" et
    "5eme", "Terminale" et "terminale", sans faux négatif dû aux
    accents."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return text.lower().strip()


def _levels_roughly_match(declared_level: str, class_name: str) -> bool:
    """Comparaison heuristique, jamais une certitude absolue — remonte les
    écarts pour qu'un humain tranche, ne décide jamais seule. Compare
    d'abord un numéro de niveau commun (6, 5, 4, 3...) ; à défaut,
    cherche un mot-clé commun (terminale, cm2, ce1, tle...)."""
    declared = _normalize_for_level_match(declared_level)
    class_n = _normalize_for_level_match(class_name)
    if not declared or not class_n:
        return False

    # Préfixe primaire (CP/CE/CM) : doit être identique des deux côtés dès
    # qu'il apparaît d'un côté — sinon "CE2" et "CM2" seraient confondus
    # par leur seul chiffre commun, dangereux dans un établissement qui va
    # du primaire au supérieur.
    declared_prefix = re.match(r"(cp|ce|cm)", declared)
    class_prefix = re.search(r"(cp|ce|cm)", class_n)
    if declared_prefix or class_prefix:
        if not (declared_prefix and class_prefix and declared_prefix.group() == class_prefix.group()):
            return False

    declared_num = re.search(r"\d+", declared)
    class_num = re.search(r"\d+", class_n)
    if declared_num and class_num:
        return declared_num.group() == class_num.group()

    declared_word = re.sub(r"[^a-z]", "", declared)
    class_word = re.sub(r"[^a-z]", "", class_n)
    if not declared_word:
        return False
    if declared_word.startswith("term") or declared_word == "tle":
        return class_word.startswith("term") or "tle" in class_word
    return declared_word[:3] in class_word


class StartOfYearCheckView(generics.ListAPIView):
    """Vérification de rentrée — pour chaque inscription active de
    l'établissement, contrôle si le niveau déclaré par l'élève correspond
    à sa classe réelle. Purement indicatif (comparaison heuristique sur du
    texte libre, jamais fiable à 100%) : remonte les écarts probables
    pour que le directeur ou un enseignant tranche, ne corrige jamais
    seule. Accessible au directeur et à tout enseignant de
    l'établissement, la correction (changement de classe) restant elle
    réservée à qui a autorité sur l'effectif (voir ClassRosterView)."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        user = request.user
        if user.has_role(UserRole.DIRECTOR):
            establishment = _director_establishment(user)
        elif user.has_role(UserRole.TEACHER):
            # Un enseignant ne voit que l'établissement où il enseigne
            # réellement (au moins une classe ou une matière), jamais la
            # liste de tous les établissements Xporadia.
            school_class = SchoolClass.objects.filter(
                Q(homeroom_teacher=user) | Q(subjects__teacher=user)
            ).select_related("track__department__establishment").first()
            if not school_class:
                raise PermissionDenied("Aucune classe associée à ce compte.")
            establishment = school_class.track.department.establishment
        else:
            raise PermissionDenied("Réservé aux enseignants et directeurs.")

        enrollments = Enrollment.objects.filter(
            school_class__track__department__establishment=establishment,
            status=EnrollmentStatus.ACTIVE,
        ).select_related("child", "school_class")

        mismatches = []
        for enrollment in enrollments:
            declared = enrollment.child.class_level
            if not declared:
                continue
            if not _levels_roughly_match(declared, enrollment.school_class.name):
                mismatches.append({
                    "enrollment": enrollment.id,
                    "child": enrollment.child.id,
                    "first_name": enrollment.child.first_name,
                    "last_name": enrollment.child.last_name,
                    "declared_level": declared,
                    "current_class": enrollment.school_class.name,
                    "current_class_id": enrollment.school_class.id,
                })
        return Response({
            "total_checked": enrollments.count(),
            "mismatches_found": len(mismatches),
            "mismatches": mismatches,
        })


class CorrectEnrollmentClassView(APIView):
    """Correction directe d'une affectation — distincte du passage de
    classe (qui change de niveau) : ici, l'élève reste au même niveau, on
    corrige juste une erreur d'aiguillage entre deux classes du même
    niveau (ex: "5ème A" au lieu de "5ème B"). Délégable, comme le reste
    de la gestion des effectifs."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, enrollment_id):
        enrollment = get_object_or_404(
            Enrollment.objects.select_related("school_class__track__department__establishment", "child"),
            pk=enrollment_id, status=EnrollmentStatus.ACTIVE,
        )
        _require_roster_access(enrollment.school_class, request.user)

        new_class_id = request.data.get("school_class_id")
        new_class = get_object_or_404(SchoolClass, pk=new_class_id)
        if (
            new_class.track.department.establishment_id
            != enrollment.school_class.track.department.establishment_id
        ):
            raise ValidationError({"school_class_id": "Doit appartenir au même établissement."})

        old_class = enrollment.school_class
        enrollment.school_class = new_class
        enrollment.save(update_fields=["school_class"])
        _notify_parent_of_enrollment_change(
            enrollment, title="Correction de classe",
            body=f"{enrollment.child.first_name} a été réaffecté(e) de {old_class} à {new_class}.",
        )
        return Response(EnrollmentSerializer(enrollment).data)
