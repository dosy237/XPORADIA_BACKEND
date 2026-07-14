from rest_framework import serializers

from apps.users.models import Child, User, UserRole

from .models import Department, Enrollment, SchoolClass, Subject, TeacherInvitation, Track


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "description", "created_at"]
        read_only_fields = ["id", "created_at"]


class TrackSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    department_id = serializers.PrimaryKeyRelatedField(
        source="department", queryset=Department.objects.all(), write_only=True
    )

    class Meta:
        model = Track
        fields = ["id", "department", "department_id", "name", "description", "created_at"]
        read_only_fields = ["id", "created_at"]


class TeacherBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email"]
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

    class Meta:
        model = Subject
        fields = [
            "id", "school_class", "name", "teacher", "teacher_email",
            "pending_invitation_email", "pending_invitation_token", "created_at",
        ]
        read_only_fields = ["id", "school_class", "created_at"]

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
