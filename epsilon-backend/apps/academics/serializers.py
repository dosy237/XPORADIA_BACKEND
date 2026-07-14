from rest_framework import serializers

from apps.users.models import User, UserRole

from .models import Department, SchoolClass, Track


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "description", "created_at"]
        read_only_fields = ["id", "created_at"]


class TrackSerializer(serializers.ModelSerializer):
    department_id = serializers.PrimaryKeyRelatedField(
        source="department", queryset=Department.objects.all(), write_only=True
    )

    class Meta:
        model = Track
        fields = ["id", "department", "department_id", "name", "description", "created_at"]
        read_only_fields = ["id", "department", "created_at"]


class HomeroomTeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email"]
        read_only_fields = fields


class SchoolClassSerializer(serializers.ModelSerializer):
    track_id = serializers.PrimaryKeyRelatedField(source="track", queryset=Track.objects.all(), write_only=True)
    homeroom_teacher = HomeroomTeacherSerializer(read_only=True)
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
        read_only_fields = ["id", "track", "created_at"]

    def validate_homeroom_teacher_email(self, user):
        if not user.has_role(UserRole.TEACHER):
            raise serializers.ValidationError("L'enseignant titulaire doit avoir le rôle enseignant.")
        return user
