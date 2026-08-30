from rest_framework import serializers

from apps.users.models import Child, User, UserRole

from .models import (
    AttendanceException,
    AttendanceSession,
    AttendanceStatus,
    Department,
    Enrollment,
    EstablishmentEvent,
    EventAudience,
    PersonalScheduleBlock,
    SchoolClass,
    Subject,
    TeacherAbsence,
    TeacherInvitation,
    TimetableSlot,
    Track,
)


class DelegateBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email", "avatar"]
        read_only_fields = fields


class DepartmentSerializer(serializers.ModelSerializer):
    track_delegates = DelegateBasicSerializer(many=True, read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "description", "track_delegates", "created_at"]
        read_only_fields = ["id", "track_delegates", "created_at"]


class TrackSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    department_id = serializers.PrimaryKeyRelatedField(
        source="department", queryset=Department.objects.all(), write_only=True
    )
    class_delegates = DelegateBasicSerializer(many=True, read_only=True)

    class Meta:
        model = Track
        fields = [
            "id", "department", "department_id", "name", "description",
            "class_delegates", "created_at",
        ]
        read_only_fields = ["id", "class_delegates", "created_at"]


class TeacherBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email", "avatar"]
        read_only_fields = fields


class SchoolClassSerializer(serializers.ModelSerializer):
    track = TrackSerializer(read_only=True)
    track_id = serializers.PrimaryKeyRelatedField(source="track", queryset=Track.objects.all(), write_only=True)
    homeroom_teacher = TeacherBasicSerializer(read_only=True)
    # Un directeur connaît l'email d'un enseignant, pas son ID interne — et
    # tant que la recherche d'enseignants côté directeur (story D-02, future)
    # n'existe pas, c'est la façon la plus simple de désigner le titulaire.
    homeroom_teacher_email = serializers.SlugRelatedField(
        slug_field="email",
        source="homeroom_teacher",
        queryset=User.objects.filter(is_active=True),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = SchoolClass
        fields = [
            "id", "track", "track_id", "name", "school_year",
            "homeroom_teacher", "homeroom_teacher_email", "capacity", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_homeroom_teacher_email(self, user):
        if not user.has_role(UserRole.TEACHER):
            raise serializers.ValidationError("L'enseignant titulaire doit avoir le rôle enseignant.")
        return user


class SubjectSerializer(serializers.ModelSerializer):
    school_class = SchoolClassSerializer(read_only=True)
    teacher = TeacherBasicSerializer(read_only=True)
    # Le titulaire connaît seulement l'email de l'enseignant qu'il veut
    # ajouter — pas son ID interne, et pas forcément un compte existant :
    # si aucun compte enseignant actif ne correspond, une TeacherInvitation
    # est créée à la place (voir _resolve_teacher_email dans views.py).
    teacher_email = serializers.EmailField(write_only=True, required=False, allow_null=True)
    pending_invitation_email = serializers.SerializerMethodField()
    pending_invitation_token = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = Subject
        fields = [
            "id", "school_class", "name", "coefficient", "category", "category_label",
            "teacher", "teacher_email", "pending_invitation_email", "pending_invitation_token",
            "created_at",
        ]
        read_only_fields = ["id", "school_class", "coefficient", "created_at"]

    def _pending_invitation(self, obj):
        return obj.invitations.filter(is_accepted=False).order_by("-created_at").first()

    def get_pending_invitation_email(self, obj):
        invitation = self._pending_invitation(obj)
        return invitation.email if invitation else None

    def get_pending_invitation_token(self, obj):
        invitation = self._pending_invitation(obj)
        return invitation.token if invitation else None


class TeacherInvitationPreviewSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    school_class_name = serializers.CharField(source="subject.school_class.name", read_only=True)
    school_name = serializers.CharField(
        source="subject.school_class.track.department.establishment.school_name", read_only=True
    )
    invited_by_name = serializers.CharField(source="invited_by.get_full_name", read_only=True)

    class Meta:
        model = TeacherInvitation
        fields = [
            "token", "email", "subject_name", "school_class_name",
            "school_name", "invited_by_name", "created_at",
        ]
        read_only_fields = fields


class ChildBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Child
        fields = ["id", "first_name", "class_level"]
        read_only_fields = fields


class EnrollmentSerializer(serializers.ModelSerializer):
    child = ChildBasicSerializer(read_only=True)
    school_class = SchoolClassSerializer(read_only=True)

    class Meta:
        model = Enrollment
        fields = ["id", "child", "school_class", "status", "enrolled_at", "ended_at"]
        read_only_fields = fields


class TimetableSlotSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    weekday_label = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = TimetableSlot
        fields = [
            "id", "school_class", "subject", "subject_name", "weekday", "weekday_label",
            "start_time", "end_time", "room", "term",
        ]
        read_only_fields = ["id", "school_class", "subject_name", "weekday_label"]

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start and end and start >= end:
            raise serializers.ValidationError("L'heure de fin doit être après l'heure de début.")
        term = attrs.get("term", getattr(self.instance, "term", None))
        school_class = getattr(self.instance, "school_class", None) or self.context.get("school_class")
        if term and school_class and term.establishment_id != school_class.track.department.establishment_id:
            raise serializers.ValidationError({"term": "Ce trimestre n'appartient pas à l'établissement de cette classe."})
        return attrs


class TeacherTimetableSlotSerializer(TimetableSlotSerializer):
    """TimetableSlotSerializer + le nom de la classe — nécessaire dès que
    des créneaux de classes différentes sont mélangés dans une même liste
    (agenda enseignant agrégé), ce que le serializer élève n'a jamais eu à
    faire puisqu'un élève n'a qu'une seule classe."""

    school_class_name = serializers.CharField(source="school_class.name", read_only=True)

    class Meta(TimetableSlotSerializer.Meta):
        fields = TimetableSlotSerializer.Meta.fields + ["school_class_name"]
        read_only_fields = TimetableSlotSerializer.Meta.read_only_fields + ["school_class_name"]


class PersonalScheduleBlockSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    weekday_label = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = PersonalScheduleBlock
        fields = [
            "id", "weekday", "weekday_label", "start_time", "end_time", "title",
            "subject", "subject_name", "valid_from", "valid_until",
        ]
        read_only_fields = ["id", "weekday_label", "subject_name"]

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start and end and start >= end:
            raise serializers.ValidationError("L'heure de fin doit être après l'heure de début.")
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if valid_from and valid_until and valid_until < valid_from:
            raise serializers.ValidationError("La date de fin de validité doit être après la date de début.")
        return attrs


class DeclareTeacherAbsenceSerializer(serializers.Serializer):
    date = serializers.DateField()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class TeacherAbsenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherAbsence
        fields = ["id", "timetable_slot", "date", "reason", "declared_by", "created_at"]
        read_only_fields = fields


class EstablishmentEventSerializer(serializers.ModelSerializer):
    event_type_label = serializers.CharField(source="get_event_type_display", read_only=True)
    # Champ écriture seule, jamais stocké tel quel : indique si l'événement
    # doit être rattaché à toute l'école (school_class=null) plutôt qu'à la
    # classe d'origine de la requête — voir ClassEventListCreateView.
    for_whole_establishment = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = EstablishmentEvent
        fields = [
            "id", "school_class", "event_type", "event_type_label", "title", "description",
            "date", "start_time", "end_time", "audience", "for_whole_establishment", "created_at",
        ]
        read_only_fields = ["id", "school_class", "event_type_label", "created_at"]

    def validate_audience(self, value):
        if not value:
            raise serializers.ValidationError("Choisissez au moins un public cible.")
        valid = {choice for choice, _ in EventAudience.choices}
        if not set(value).issubset(valid):
            raise serializers.ValidationError("Public cible invalide.")
        return value

    def validate(self, attrs):
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        if start and end and start >= end:
            raise serializers.ValidationError("L'heure de fin doit être après l'heure de début.")
        return attrs


class AttendanceExceptionInputSerializer(serializers.Serializer):
    """Une ligne d'exception à saisir — jamais une ligne par élève présent
    (voir AttendanceStatus) : seuls les élèves effectivement absents, en
    retard ou excusés sont envoyés, ce qui garde l'appel d'une classe de
    40 élèves rapide (quelques envois au lieu de 40)."""

    child = serializers.IntegerField()
    status = serializers.ChoiceField(choices=AttendanceStatus.choices)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class RosterAttendanceEntrySerializer(serializers.Serializer):
    """Une ligne de la liste d'appel — présent par défaut (status=None),
    l'exception (le cas échéant) écrasant ce statut par défaut."""

    child = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=AttendanceStatus.choices, allow_null=True)
    reason = serializers.CharField(allow_blank=True)
