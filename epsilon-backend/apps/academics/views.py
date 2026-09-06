import re
import unicodedata
from datetime import date, timedelta

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
    AttendanceException,
    AttendanceSession,
    AttendanceStatus,
    DelegatedTask,
    Department,
    Enrollment,
    EnrollmentStatus,
    EstablishmentEvent,
    EventAudience,
    EventType,
    PersonalScheduleBlock,
    PersonalScheduleException,
    SchoolClass,
    Subject,
    TaskDelegation,
    TeacherAbsence,
    TeacherInvitation,
    TimetableSlot,
    Track,
)
from .serializers import (
    AttendanceExceptionInputSerializer,
    ChildBasicSerializer,
    DeclareTeacherAbsenceSerializer,
    DepartmentSerializer,
    EnrollmentSerializer,
    EstablishmentEventSerializer,
    PersonalScheduleBlockSerializer,
    RosterAttendanceEntrySerializer,
    SchoolClassSerializer,
    SubjectSerializer,
    TeacherAbsenceSerializer,
    TeacherInvitationPreviewSerializer,
    TeacherTimetableSlotSerializer,
    TimetableSlotSerializer,
    TrackSerializer,
)
from .services import (
    events_for_date,
    personal_blocks_for_date,
    teacher_timetable_slots_for_date,
    term_for_date,
    timetable_slots_for_date,
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
        subject_name = serializer.validated_data.pop("homeroom_subject_name", "").strip()
        school_class = serializer.save()
        if school_class.homeroom_teacher_id:
            self._notify_and_grant_homeroom(school_class, previous_teacher_id=None, subject_name=subject_name)

    def perform_update(self, serializer):
        self._validate_track_ownership(serializer)
        subject_name = serializer.validated_data.pop("homeroom_subject_name", "").strip()
        previous_teacher_id = serializer.instance.homeroom_teacher_id
        school_class = serializer.save()
        if school_class.homeroom_teacher_id != previous_teacher_id:
            self._notify_and_grant_homeroom(school_class, previous_teacher_id, subject_name=subject_name)

    def _notify_and_grant_homeroom(self, school_class, previous_teacher_id, subject_name=""):
        """Nomination (ou changement) de titulaire — notifie le nouveau
        titulaire, transfère les droits d'administration du canal de
        classe (qui ne se mettent jamais à jour tout seuls sinon : le
        titulaire précédent resterait admin indéfiniment), et lui rattache
        sa propre matière dans cette classe si le directeur en a précisé
        une : un titulaire est d'abord un enseignant, jamais un rôle
        déconnecté de l'enseignement réel (voir Subject.teacher, dont
        dépend l'agrégation de l'emploi du temps personnel du professeur)."""
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
            if subject_name:
                Subject.objects.update_or_create(
                    school_class=school_class, name=subject_name, defaults={"teacher": new_teacher}
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


def _require_slot_attendance_access(slot, user):
    """Enseignant dédié de la matière de CE créneau (celui qui fait
    réellement cours), titulaire de la classe, ou directeur — jamais
    l'enseignant délégué pour les emplois du temps, qui n'a aucune
    légitimité pédagogique sur un cours qu'il ne donne pas lui-même."""
    if slot.subject.teacher_id == user.id:
        return
    if slot.school_class.homeroom_teacher_id == user.id:
        return
    establishment = slot.school_class.track.department.establishment
    if user.has_role(UserRole.DIRECTOR) and establishment.user_id == user.id:
        return
    raise PermissionDenied(
        "Réservé à l'enseignant de cette matière, au titulaire de la classe, ou au directeur de l'établissement."
    )


def _require_own_slot_teacher(slot, user):
    """Seul l'enseignant dédié de CETTE matière peut déclarer sa propre
    absence sur ce créneau — jamais le titulaire ni le directeur à sa
    place, qui n'ont pas la légitimité de décider si LUI tient cours ou
    non (distinct de _require_slot_attendance_access, qui couvre l'appel,
    un geste que le titulaire ou le directeur peuvent légitimement faire
    à sa place)."""
    if slot.subject.teacher_id != user.id:
        raise PermissionDenied("Seul l'enseignant dédié de cette matière peut déclarer une absence sur ce créneau.")


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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["school_class"] = _get_school_class(self.kwargs["class_id"])
        return context

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


def _require_child_profile(user):
    child = getattr(user, "child_profile", None)
    if not child:
        raise PermissionDenied("Réservé aux comptes élève.")
    return child


def _parse_date_param(raw, field="date"):
    if not raw:
        raise ValidationError({field: "Ce paramètre est requis (format YYYY-MM-DD)."})
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({field: "Format invalide, attendu YYYY-MM-DD."})


class MyAgendaView(APIView):
    """Agenda d'une journée pour l'élève connecté : cours officiels de sa
    classe (lecture seule, vides si la date tombe en vacances — voir
    apps.academics.services.timetable_slots_for_date) + ses créneaux
    personnels (toujours affichés, jour d'école ou non)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = _require_child_profile(request.user)
        raw_date = request.query_params.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()

        enrollment = Enrollment.objects.filter(
            child=child, status=EnrollmentStatus.ACTIVE
        ).select_related("school_class__track__department__establishment").first()

        official_slots = []
        school_events = []
        term = None
        if enrollment:
            school_class = enrollment.school_class
            official_slots = TimetableSlotSerializer(
                timetable_slots_for_date(school_class, target_date), many=True
            ).data
            establishment = school_class.track.department.establishment
            school_events = EstablishmentEventSerializer(
                events_for_date(establishment, school_class, target_date, EventAudience.STUDENTS), many=True
            ).data
            if target_date.weekday() <= 5:
                term = term_for_date(establishment, school_class.school_year, target_date)

        return Response({
            "date": target_date.isoformat(),
            "weekday": target_date.weekday(),
            "is_school_day": term is not None,
            "term": (
                {"id": term.id, "number": term.number, "name": term.name}
                if term else None
            ),
            "official_slots": official_slots,
            "personal_blocks": personal_blocks_for_date(child, target_date),
            "school_events": school_events,
        })


def _teacher_is_school_day(user, target_date):
    """"Jour d'école" pour l'enseignant = au moins une de ses classes a un
    trimestre couvrant cette date — distinct de "l'enseignant a
    personnellement un cours ce jour-là" (ce dernier peut être faux un
    jour d'école normal, ex. mercredi sans créneau pour lui)."""
    if target_date.weekday() > 5:
        return False
    class_ids = Subject.objects.filter(teacher=user).values_list("school_class_id", flat=True).distinct()
    for school_class in SchoolClass.objects.filter(id__in=class_ids).select_related(
        "track__department__establishment"
    ):
        establishment = school_class.track.department.establishment
        if term_for_date(establishment, school_class.school_year, target_date):
            return True
    return False


class MyTeacherAgendaView(APIView):
    """Agenda d'une journée pour l'enseignant connecté, agrégeant TOUTES
    ses classes (celles où il est enseignant dédié d'une matière) — jamais
    une classe à la fois. Miroir de MyAgendaView côté élève, mais sans
    créneaux personnels ni notion de "ma classe" unique : un enseignant
    dédié n'a pas de créneaux personnels ici, et school_events est laissé
    vide (les événements sont déjà consultables par classe ailleurs, une
    agrégation multi-classes n'aurait pas de calendrier d'audience simple
    à filtrer)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        raw_date = request.query_params.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()

        slots = teacher_timetable_slots_for_date(request.user, target_date)
        official_slots = TeacherTimetableSlotSerializer(slots, many=True).data

        return Response({
            "date": target_date.isoformat(),
            "weekday": target_date.weekday(),
            "is_school_day": _teacher_is_school_day(request.user, target_date),
            "official_slots": official_slots,
        })


def _get_timetable_slot(slot_id):
    try:
        return TimetableSlot.objects.select_related(
            "subject", "school_class__track__department__establishment"
        ).get(pk=slot_id)
    except TimetableSlot.DoesNotExist:
        raise Http404


def _attendance_roster(school_class, session, request):
    """Liste d'appel complète : tous les élèves activement inscrits,
    présents par défaut (status=None), les exceptions de la session (s'il
    y en a une) écrasant ce statut par défaut — jamais l'inverse."""
    exceptions_by_child = {}
    if session:
        exceptions_by_child = {
            exc.child_id: exc for exc in session.exceptions.all()
        }
    enrollments = Enrollment.objects.filter(
        school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).select_related("child", "child__user").order_by("child__last_name", "child__first_name")

    roster = []
    for enrollment in enrollments:
        child = enrollment.child
        exc = exceptions_by_child.get(child.id)
        avatar = None
        if child.user_id and child.user.avatar:
            avatar = request.build_absolute_uri(child.user.avatar.url)
        roster.append({
            "child": child.id,
            "first_name": child.first_name,
            "last_name": child.last_name,
            "avatar": avatar,
            "status": exc.status if exc else None,
            "reason": exc.reason if exc else "",
        })
    return roster


class SlotAttendanceView(APIView):
    """Appel d'un créneau précis à une date précise — tous les élèves
    inscrits sont présents par défaut, seule une exception (absent, en
    retard, excusé) doit être saisie explicitement. GET renvoie l'état
    actuel (jamais écrit en base tant qu'aucun appel n'a été fait sur ce
    créneau/cette date) ; POST enregistre l'appel complet en un seul
    envoi — jamais un aller-retour réseau par élève, essentiel pour une
    classe de 40 élèves."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slot_id):
        slot = _get_timetable_slot(slot_id)
        _require_slot_attendance_access(slot, request.user)
        raw_date = request.query_params.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()

        session = AttendanceSession.objects.filter(timetable_slot=slot, date=target_date).select_related(
            "taken_by"
        ).prefetch_related("exceptions").first()
        absence = TeacherAbsence.objects.filter(timetable_slot=slot, date=target_date).first()

        return Response({
            "date": target_date.isoformat(),
            "taken": session is not None,
            "taken_by": session.taken_by.get_full_name() if session and session.taken_by else None,
            "taken_at": session.updated_at.isoformat() if session else None,
            "cancelled": absence is not None,
            "cancelled_reason": absence.reason if absence else "",
            "roster": RosterAttendanceEntrySerializer(
                _attendance_roster(slot.school_class, session, request), many=True
            ).data,
        })

    def post(self, request, slot_id):
        slot = _get_timetable_slot(slot_id)
        _require_slot_attendance_access(slot, request.user)
        raw_date = request.data.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()

        if TeacherAbsence.objects.filter(timetable_slot=slot, date=target_date).exists():
            raise ValidationError("Ce cours a été annulé pour cette date : impossible de faire l'appel.")

        entries_serializer = AttendanceExceptionInputSerializer(data=request.data.get("exceptions", []), many=True)
        entries_serializer.is_valid(raise_exception=True)
        entries = entries_serializer.validated_data

        valid_child_ids = set(
            Enrollment.objects.filter(
                school_class=slot.school_class, status=EnrollmentStatus.ACTIVE
            ).values_list("child_id", flat=True)
        )
        for entry in entries:
            if entry["child"] not in valid_child_ids:
                raise ValidationError({"exceptions": f"L'élève {entry['child']} n'est pas inscrit dans cette classe."})

        session, _ = AttendanceSession.objects.get_or_create(
            timetable_slot=slot, date=target_date,
            defaults={"taken_by": request.user, "created_by": request.user},
        )
        session.taken_by = request.user
        session.save(update_fields=["taken_by", "updated_at"])

        # Remplace systématiquement l'ensemble des exceptions par l'envoi
        # reçu — le frontend renvoie toujours la liste complète des
        # exceptions actuelles, jamais un delta, ce qui rend une
        # correction (élève finalement présent) aussi simple qu'un ajout.
        session.exceptions.all().delete()
        AttendanceException.objects.bulk_create([
            AttendanceException(
                session=session, child_id=entry["child"], status=entry["status"], reason=entry.get("reason", "")
            )
            for entry in entries
        ])

        session.refresh_from_db()
        return Response({
            "date": target_date.isoformat(),
            "taken": True,
            "taken_by": request.user.get_full_name(),
            "taken_at": session.updated_at.isoformat(),
            "roster": RosterAttendanceEntrySerializer(
                _attendance_roster(slot.school_class, session, request), many=True
            ).data,
        })


class TeacherAttendanceOverviewView(APIView):
    """Créneaux du jour pour l'enseignant connecté (mêmes classes que
    MyTeacherAgendaView), chacun annoté de l'état de son appel — pour
    afficher d'un coup d'œil lesquels restent à faire."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        raw_date = request.query_params.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()

        slots = teacher_timetable_slots_for_date(request.user, target_date)
        sessions_by_slot = {
            s.timetable_slot_id: s
            for s in AttendanceSession.objects.filter(
                timetable_slot__in=slots, date=target_date
            ).prefetch_related("exceptions")
        }
        cancelled_slot_ids = set(
            TeacherAbsence.objects.filter(
                timetable_slot__in=slots, date=target_date
            ).values_list("timetable_slot_id", flat=True)
        )

        data = TeacherTimetableSlotSerializer(slots, many=True).data
        for slot_data, slot in zip(data, slots):
            session = sessions_by_slot.get(slot.id)
            slot_data["attendance_taken"] = session is not None
            slot_data["attendance_exceptions_count"] = len(session.exceptions.all()) if session else 0
            slot_data["cancelled"] = slot.id in cancelled_slot_ids

        return Response({
            "date": target_date.isoformat(),
            "weekday": target_date.weekday(),
            "is_school_day": _teacher_is_school_day(request.user, target_date),
            "slots": data,
        })


def _notify_teacher_absence(absence):
    """Notifie titulaire et directeur (équipe), puis élèves et parents de
    la classe (élève directement s'il a un compte actif, parent EN PLUS
    s'il est rattaché, jamais l'un à la place de l'autre) qu'un cours ne
    sera pas tenu — même principe que _notify_holiday_declared."""
    slot = absence.timetable_slot
    school_class = slot.school_class
    subject = slot.subject
    date_label = absence.date.strftime("%d/%m/%Y")
    teacher_name = subject.teacher.get_full_name() if subject.teacher_id else "L'enseignant dédié"

    staff_body = f"{teacher_name} ne tiendra pas le cours de {subject.name} ({school_class}) du {date_label}."
    if absence.reason:
        staff_body += f" Motif : {absence.reason}"

    staff_recipients = []
    if school_class.homeroom_teacher_id and school_class.homeroom_teacher_id != subject.teacher_id:
        staff_recipients.append(school_class.homeroom_teacher)
    establishment = school_class.track.department.establishment
    if establishment.user_id and establishment.user_id != subject.teacher_id:
        staff_recipients.append(establishment.user)
    for recipient in staff_recipients:
        notify_user(
            recipient, NotificationType.SESSION_CANCELLED,
            title="Cours annulé",
            body=staff_body,
            data={"timetable_slot_id": slot.id, "date": absence.date.isoformat()},
        )

    student_body = f"Le cours de {subject.name} du {date_label} n'aura pas lieu."
    enrollments = Enrollment.objects.filter(
        school_class=school_class, status=EnrollmentStatus.ACTIVE
    ).select_related("child__user", "child__parent__user")
    for enrollment in enrollments:
        child = enrollment.child
        recipients = []
        if child.user_id:
            recipients.append(child.user)
        if child.parent_id and child.parent.user_id:
            recipients.append(child.parent.user)
        for recipient in recipients:
            notify_user(
                recipient, NotificationType.SESSION_CANCELLED,
                title="Cours annulé",
                body=student_body,
                data={"timetable_slot_id": slot.id, "date": absence.date.isoformat()},
            )


class TeacherAbsenceDeclarationView(APIView):
    """Déclaration par l'enseignant dédié qu'il ne tiendra pas ce créneau à
    une date précise. Réutilise EstablishmentEvent pour représenter le
    cours annulé sur l'agenda de la classe plutôt qu'un système
    d'affichage parallèle (voir TeacherAbsence.event). DELETE annule la
    déclaration (l'enseignant peut finalement assurer le cours)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slot_id):
        slot = _get_timetable_slot(slot_id)
        _require_own_slot_teacher(slot, request.user)

        serializer = DeclareTeacherAbsenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_date = serializer.validated_data["date"]
        reason = serializer.validated_data.get("reason", "")

        if not timetable_slots_for_date(slot.school_class, target_date).filter(id=slot.id).exists():
            raise ValidationError("Ce créneau n'a pas lieu à cette date.")
        if TeacherAbsence.objects.filter(timetable_slot=slot, date=target_date).exists():
            raise ValidationError("Une absence a déjà été déclarée sur ce créneau à cette date.")

        establishment = slot.school_class.track.department.establishment
        event = EstablishmentEvent.objects.create(
            establishment=establishment,
            school_class=slot.school_class,
            event_type=EventType.CANCELLED_CLASS,
            title=slot.subject.name,
            description=reason,
            date=target_date,
            start_time=slot.start_time,
            end_time=slot.end_time,
            audience=[EventAudience.STUDENTS, EventAudience.PARENTS],
            created_by=request.user,
        )
        absence = TeacherAbsence.objects.create(
            timetable_slot=slot, date=target_date, reason=reason, declared_by=request.user, event=event,
        )
        _notify_teacher_absence(absence)
        return Response(TeacherAbsenceSerializer(absence).data, status=status.HTTP_201_CREATED)

    def delete(self, request, slot_id):
        slot = _get_timetable_slot(slot_id)
        _require_own_slot_teacher(slot, request.user)
        raw_date = request.query_params.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()
        try:
            absence = TeacherAbsence.objects.select_related("event").get(timetable_slot=slot, date=target_date)
        except TeacherAbsence.DoesNotExist:
            raise Http404
        absence.event.delete()  # cascade supprime aussi la ligne TeacherAbsence
        return Response(status=status.HTTP_204_NO_CONTENT)


class PersonalScheduleBlockListCreateView(generics.ListCreateAPIView):
    """Créneaux personnels récurrents de l'élève connecté. La création
    ouvre une nouvelle règle récurrente ; la modification/suppression d'une
    occurrence précise passe par PersonalScheduleBlockOccurrenceView, qui
    impose de choisir explicitement le mode (cette date seule, ou cette
    date et les suivantes)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PersonalScheduleBlockSerializer
    pagination_class = None

    def get_queryset(self):
        child = _require_child_profile(self.request.user)
        return PersonalScheduleBlock.objects.filter(child=child).select_related("subject")

    def perform_create(self, serializer):
        child = _require_child_profile(self.request.user)
        serializer.save(child=child)


class PersonalScheduleBlockOccurrenceView(APIView):
    """Modifie ou supprime UNE occurrence d'un créneau personnel récurrent.
    Le frontend doit toujours transmettre `scope` ("this" ou "following") —
    jamais de valeur par défaut assumée côté serveur :
      - "this" : crée/écrase l'exception ponctuelle de cette date, sans
        toucher la règle récurrente.
      - "following" : clôt la règle actuelle à la veille de cette date et
        ouvre une nouvelle règle à partir de cette date avec les nouvelles
        valeurs (ou, si cette date est justement le tout premier jour de
        validité de la règle, modifie la règle en place — inutile d'en
        ouvrir une seconde puisqu'aucune occurrence antérieure n'existe)."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_block(self, pk, user):
        child = _require_child_profile(user)
        return get_object_or_404(PersonalScheduleBlock, pk=pk, child=child)

    def _validated_target_date(self, block, request_data_or_params):
        scope = request_data_or_params.get("scope")
        if scope not in ("this", "following"):
            raise ValidationError({"scope": "Requis, 'this' ou 'following'."})
        target_date = _parse_date_param(request_data_or_params.get("date"))
        if target_date < block.valid_from or (block.valid_until and target_date > block.valid_until):
            raise ValidationError({"date": "Cette date ne fait pas partie de ce créneau."})
        return scope, target_date

    def patch(self, request, pk):
        block = self._get_block(pk, request.user)
        scope, target_date = self._validated_target_date(block, request.data)

        title = request.data.get("title", "")
        subject_id = request.data.get("subject")
        start_time = request.data.get("start_time") or None
        end_time = request.data.get("end_time") or None

        if scope == "this":
            exception, _created = PersonalScheduleException.objects.update_or_create(
                block=block, date=target_date,
                defaults={
                    "is_cancelled": False,
                    "title": title,
                    "subject_id": subject_id or None,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            )
            return Response({
                "id": exception.id, "date": exception.date.isoformat(), "title": exception.title,
                "subject": exception.subject_id, "start_time": exception.start_time, "end_time": exception.end_time,
            }, status=status.HTTP_200_OK)

        if target_date == block.valid_from:
            if title:
                block.title = title
            if subject_id is not None:
                block.subject_id = subject_id or None
            if start_time:
                block.start_time = start_time
            if end_time:
                block.end_time = end_time
            block.save()
            return Response(PersonalScheduleBlockSerializer(block).data, status=status.HTTP_200_OK)

        block.valid_until = target_date - timedelta(days=1)
        block.save(update_fields=["valid_until"])
        new_block = PersonalScheduleBlock.objects.create(
            child=block.child,
            weekday=block.weekday,
            start_time=start_time or block.start_time,
            end_time=end_time or block.end_time,
            title=title or block.title,
            subject_id=subject_id if subject_id is not None else block.subject_id,
            valid_from=target_date,
            valid_until=None,
        )
        return Response(PersonalScheduleBlockSerializer(new_block).data, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        block = self._get_block(pk, request.user)
        scope, target_date = self._validated_target_date(block, request.query_params)

        if scope == "this":
            PersonalScheduleException.objects.update_or_create(
                block=block, date=target_date,
                defaults={"is_cancelled": True, "title": "", "subject_id": None, "start_time": None, "end_time": None},
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        if target_date <= block.valid_from:
            block.delete()
        else:
            block.valid_until = target_date - timedelta(days=1)
            block.save(update_fields=["valid_until"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def _notify_holiday_declared(event):
    """Notifie immédiatement les élèves concernés par un jour férié
    nouvellement déclaré, et leurs parents s'ils sont rattachés — même
    principe que partout ailleurs (élève directement s'il a un compte
    actif, parent EN PLUS s'il est rattaché, jamais l'un à la place de
    l'autre). Portée établissement entière si event.school_class est nul,
    sinon limitée à cette classe."""
    enrollments = Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE).select_related(
        "child__user", "child__parent__user"
    )
    if event.school_class_id:
        enrollments = enrollments.filter(school_class_id=event.school_class_id)
    else:
        enrollments = enrollments.filter(school_class__track__department__establishment=event.establishment)

    body = f"{event.title} — {event.date.strftime('%d/%m/%Y')}."
    for enrollment in enrollments:
        child = enrollment.child
        recipients = []
        if child.user_id:
            recipients.append(child.user)
        if child.parent_id and child.parent.user_id:
            recipients.append(child.parent.user)
        for recipient in recipients:
            notify_user(
                recipient,
                NotificationType.HOLIDAY_DECLARED,
                title="Jour férié",
                body=body,
                data={"event_id": str(event.id), "date": event.date.isoformat()},
            )


class ClassEventListCreateView(generics.ListCreateAPIView):
    """Événements d'établissement (remise de bulletins, réunion, jour
    férié, autre) rattachés à cette classe, plus ceux déclarés pour tout
    l'établissement — vue de gestion côté enseignant/directeur, atteinte
    depuis l'écran de classe existant. Un jour férié réutilise
    _require_timetable_write_access (mêmes ayants droit que l'emploi du
    temps) ; les autres types réutilisent _require_homeroom_teacher
    (titulaire ou directeur), aucune logique de permission nouvelle."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EstablishmentEventSerializer
    pagination_class = None

    def get_queryset(self):
        school_class = _get_school_class(self.kwargs["class_id"])
        _require_timetable_write_access(school_class, self.request.user)
        establishment = school_class.track.department.establishment
        return EstablishmentEvent.objects.filter(establishment=establishment).filter(
            Q(school_class__isnull=True) | Q(school_class=school_class)
        )

    def perform_create(self, serializer):
        school_class = _get_school_class(self.kwargs["class_id"])
        event_type = serializer.validated_data["event_type"]
        if event_type == EventType.HOLIDAY:
            _require_timetable_write_access(school_class, self.request.user)
        else:
            _require_homeroom_teacher(school_class, self.request.user)

        establishment = school_class.track.department.establishment
        for_whole_establishment = serializer.validated_data.pop("for_whole_establishment", False)
        instance = serializer.save(
            establishment=establishment,
            school_class=None if for_whole_establishment else school_class,
            created_by=self.request.user,
        )
        if instance.event_type == EventType.HOLIDAY:
            _notify_holiday_declared(instance)


class ChildEventsView(generics.ListAPIView):
    """Événements d'établissement pertinents pour le parent connecté, sur
    une date donnée — lecture seule, réutilise events_for_date avec le
    public cible \"parents\" (jamais un événement ciblant uniquement
    l'équipe enseignante)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EstablishmentEventSerializer
    pagination_class = None

    def get_queryset(self):
        child = _require_child_belongs_to_parent(self.kwargs["child_id"], self.request.user)
        raw_date = self.request.query_params.get("date")
        target_date = _parse_date_param(raw_date) if raw_date else timezone.localdate()
        enrollment = Enrollment.objects.filter(
            child=child, status=EnrollmentStatus.ACTIVE
        ).select_related("school_class__track__department__establishment").first()
        if not enrollment:
            return EstablishmentEvent.objects.none()
        school_class = enrollment.school_class
        establishment = school_class.track.department.establishment
        events = events_for_date(establishment, school_class, target_date, EventAudience.PARENTS)
        return EstablishmentEvent.objects.filter(id__in=[e.id for e in events])


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
                "school_class_name": None, "homeroom_teacher": None, "classmates": [], "subjects": [],
                "establishment_name": None, "class_level": child.class_level, "status": None,
                "birth_date": child.birth_date,
            })

        school_class = enrollment.school_class
        classmates = (
            Enrollment.objects.filter(school_class=school_class, status=EnrollmentStatus.ACTIVE)
            .exclude(child=child)
            .select_related("child__user")
            .order_by("child__first_name")
        )
        teacher = school_class.homeroom_teacher

        from apps.messaging.models import Channel, ChannelType

        subjects = Subject.objects.filter(school_class=school_class).select_related("teacher").order_by("name")
        subject_channel_by_id = dict(
            Channel.objects.filter(channel_type=ChannelType.SUBJECT, subject__in=subjects).values_list(
                "subject_id", "id"
            )
        )

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
                    {
                        "id": e.child.id, "first_name": e.child.first_name, "last_name": e.child.last_name,
                        "avatar": (
                            request.build_absolute_uri(e.child.user.avatar.url)
                            if e.child.user_id and e.child.user.avatar else None
                        ),
                        "can_message": bool(e.child.user_id),
                    }
                    for e in classmates
                ],
                "subjects": [
                    {
                        "id": subject.id, "name": subject.name,
                        "teacher_name": subject.teacher.get_full_name() if subject.teacher else None,
                        "channel_id": subject_channel_by_id.get(subject.id),
                    }
                    for subject in subjects
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


class TeachingStaffOverviewView(generics.ListAPIView):
    """Vue d'ensemble de l'équipe enseignante de l'établissement : tout
    enseignant titulaire d'au moins une classe ou dédié à au moins une
    matière de cet établissement (jamais l'annuaire public des
    enseignants Xporadia — TeacherDirectoryViewSet — qui ne donne accès
    ni aux coordonnées ni au rattachement réel à un établissement).
    Chaque contrat (apps.employment.Recruitment) éventuellement associé
    est ajouté à titre indicatif, sans jamais en dépendre : un
    enseignant affecté à une classe reste dans la liste même sans
    contrat enregistré."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        _require_director(request.user)
        establishment = _director_establishment(request.user)

        teachers = User.objects.filter(
            Q(homeroom_classes__track__department__establishment=establishment)
            | Q(dedicated_subjects__school_class__track__department__establishment=establishment)
        ).distinct().select_related("teacher_profile")

        from apps.certification.constants import badge_for_points
        from apps.certification.models import CertificationLevel
        from apps.certification.services import teacher_total_points
        from apps.employment.models import Recruitment

        recruitments = {
            r.teacher_id: r
            for r in Recruitment.objects.filter(school=request.user, teacher__in=teachers)
        }

        data = []
        for teacher in teachers:
            homeroom_classes = SchoolClass.objects.filter(
                homeroom_teacher=teacher, track__department__establishment=establishment
            )
            subjects = Subject.objects.filter(
                teacher=teacher, school_class__track__department__establishment=establishment
            ).select_related("school_class")

            level = badge_for_points(teacher_total_points(teacher))
            recruitment = recruitments.get(teacher.id)

            data.append({
                "id": teacher.id,
                "first_name": teacher.first_name,
                "last_name": teacher.last_name,
                "avatar": request.build_absolute_uri(teacher.avatar.url) if teacher.avatar else None,
                "phone": teacher.phone,
                "email": teacher.email,
                "certification_level": level,
                "certification_level_label": CertificationLevel(level).label,
                "homeroom_classes": [str(c) for c in homeroom_classes],
                "subjects": [
                    {"name": s.name, "class_name": str(s.school_class)} for s in subjects
                ],
                "recruitment": {
                    "contract_type": recruitment.contract_type,
                    "contract_type_label": recruitment.get_contract_type_display(),
                    "hourly_rate_teacher": recruitment.hourly_rate_teacher,
                } if recruitment else None,
            })

        data.sort(key=lambda t: (t["last_name"], t["first_name"]))
        return Response(data)


def _student_avatar_url(request, child):
    """Même convention que apps.grading (roster/bulletins) : la photo
    n'existe que si l'élève a activé son propre compte, jamais stockée
    directement sur Child."""
    if child.user_id and child.user.avatar:
        return request.build_absolute_uri(child.user.avatar.url)
    return None


class EstablishmentStudentsView(generics.ListAPIView):
    """Vue d'ensemble et recherche des élèves de l'établissement, toutes
    classes confondues — jamais paginée (convention déjà suivie par
    toutes les listes de cette app), avec recherche par nom ou
    matricule via ?q=. Sert de point d'entrée pour joindre directement
    un élève sans passer par les effectifs d'une classe (seul chemin
    existant jusqu'ici vers les fiches frais/documents/discipline)."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        _require_director(request.user)
        establishment = _director_establishment(request.user)

        enrollments = Enrollment.objects.filter(
            school_class__track__department__establishment=establishment,
            status=EnrollmentStatus.ACTIVE,
        ).select_related("child", "child__user", "school_class")

        query = request.query_params.get("q", "").strip()
        if query:
            enrollments = enrollments.filter(
                Q(child__first_name__icontains=query)
                | Q(child__last_name__icontains=query)
                | Q(child__matricule__icontains=query)
            )

        data = [
            {
                "id": enrollment.child.id,
                "first_name": enrollment.child.first_name,
                "last_name": enrollment.child.last_name,
                "avatar": _student_avatar_url(request, enrollment.child),
                "matricule": enrollment.child.matricule,
                "class_name": str(enrollment.school_class),
                "school_year": enrollment.school_class.school_year,
            }
            for enrollment in enrollments
        ]
        data.sort(key=lambda s: (s["last_name"], s["first_name"]))
        return Response(data)


class StudentOverviewView(APIView):
    """Fiche d'ensemble d'un élève de l'établissement : identité,
    inscription courante, contact du parent — réservé au directeur de
    l'établissement où l'élève est inscrit."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, child_id):
        _require_director(request.user)
        establishment = _director_establishment(request.user)

        enrollment = Enrollment.objects.filter(
            child_id=child_id,
            status=EnrollmentStatus.ACTIVE,
            school_class__track__department__establishment=establishment,
        ).select_related("child__user", "child__parent__user", "school_class").first()
        if not enrollment:
            raise Http404

        child = enrollment.child
        parent = child.parent

        return Response({
            "id": child.id,
            "first_name": child.first_name,
            "last_name": child.last_name,
            "avatar": _student_avatar_url(request, child),
            "matricule": child.matricule,
            "birth_date": child.birth_date,
            "birth_place": child.birth_place,
            "sex_label": child.get_sex_display(),
            "nationality": child.nationality,
            "class_name": str(enrollment.school_class),
            "school_year": enrollment.school_class.school_year,
            "parent_name": parent.user.get_full_name() if parent else "",
            "parent_phone": parent.user.phone if parent else "",
            "parent_email": parent.user.email if parent else "",
        })
