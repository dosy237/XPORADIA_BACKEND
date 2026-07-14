from rest_framework import serializers

from apps.users.models import User, UserRole

from .models import Department, SchoolClass, Subject, Track


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
    # Le titulaire connaît l'email de l'enseignant qu'il veut ajouter/inviter
    # sur la matière, pas son ID interne — même logique que homeroom_teacher_email.
    teacher_email = serializers.SlugRelatedField(
        slug_field="email",
        source="teacher",
        queryset=User.objects.filter(is_active=True),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Subject
        fields = ["id", "school_class", "name", "teacher", "teacher_email", "created_at"]
        read_only_fields = ["id", "school_class", "created_at"]

    def validate_teacher_email(self, user):
        if not user.has_role(UserRole.TEACHER):
            raise serializers.ValidationError("L'enseignant dédié doit avoir le rôle enseignant.")
        return user
