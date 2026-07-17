from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    Child,
    CompanyProfile,
    DirectorProfile,
    ParentProfile,
    PreRegistrationCode,
    TeacherComment,
    TeacherProfile,
    User,
    UserRole,
)


class UserSerializer(serializers.ModelSerializer):
    all_roles = serializers.ListField(source="get_all_roles", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "phone", "first_name", "last_name", "avatar",
            "primary_role", "secondary_roles", "all_roles",
            "is_verified", "is_documents_validated", "two_fa_enabled", "created_at",
            "profile_visible", "notify_email", "notify_sms", "notify_push",
        ]
        read_only_fields = fields


class BaseRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField()
    last_name = serializers.CharField()

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Un compte existe déjà avec cet email.")
        return value

    def create_user(self, role: str) -> User:
        validated_data = self.validated_data
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            phone=validated_data.get("phone", ""),
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            primary_role=role,
        )


class RegisterTeacherSerializer(BaseRegisterSerializer):
    subjects = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    experience_years = serializers.IntegerField(required=False, default=0, min_value=0)
    location = serializers.CharField(required=False, allow_blank=True, default="")
    identity_document = serializers.FileField(required=False, allow_null=True)

    def create(self):
        user = self.create_user(UserRole.TEACHER)
        TeacherProfile.objects.create(
            user=user,
            subjects=self.validated_data.get("subjects", []),
            experience_years=self.validated_data.get("experience_years", 0),
            location=self.validated_data.get("location", ""),
            identity_document=self.validated_data.get("identity_document"),
            # Un enseignant qui vient de s'inscrire n'est pas encore accrédité
            # (formation présentielle + code de préinscription à valider) : il
            # ne doit pas apparaître comme disponible pour le recrutement tant
            # que Xporadia n'a pas validé son dossier.
            available_for_employment=False,
        )
        return user


class RegisterDirectorSerializer(BaseRegisterSerializer):
    school_name = serializers.CharField()
    address = serializers.CharField()
    levels_taught = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    student_count = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    legal_documents = serializers.FileField(required=False, allow_null=True)

    def create(self):
        user = self.create_user(UserRole.DIRECTOR)
        DirectorProfile.objects.create(
            user=user,
            school_name=self.validated_data["school_name"],
            address=self.validated_data["address"],
            levels_taught=self.validated_data.get("levels_taught", []),
            student_count=self.validated_data.get("student_count"),
            legal_documents=self.validated_data.get("legal_documents"),
        )
        return user


class RegisterCompanySerializer(BaseRegisterSerializer):
    company_name = serializers.CharField()
    sector = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField()
    legal_documents = serializers.FileField(required=False, allow_null=True)

    def create(self):
        user = self.create_user(UserRole.COMPANY)
        CompanyProfile.objects.create(
            user=user,
            company_name=self.validated_data["company_name"],
            sector=self.validated_data.get("sector", ""),
            address=self.validated_data["address"],
            legal_documents=self.validated_data.get("legal_documents"),
        )
        return user


class ChildSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    class_level = serializers.CharField()
    target_subjects = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class RegisterParentSerializer(BaseRegisterSerializer):
    location = serializers.CharField(required=False, allow_blank=True, default="")
    children = ChildSerializer(many=True, required=False, default=list)

    def validate_children(self, value):
        if len(value) > 5:
            raise serializers.ValidationError("Maximum 5 enfants à l'inscription.")
        return value

    def create(self):
        user = self.create_user(UserRole.PARENT)
        parent_profile = ParentProfile.objects.create(
            user=user, location=self.validated_data.get("location", "")
        )
        Child.objects.bulk_create(
            [
                Child(parent=parent_profile, **child_data)
                for child_data in self.validated_data.get("children", [])
            ]
        )
        return user


class TeacherProfileSerializer(serializers.ModelSerializer):
    is_documents_validated = serializers.BooleanField(source="user.is_documents_validated", read_only=True)
    preregistration_code_submitted = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = [
            "subjects", "experience_years", "hourly_rate", "location", "bio",
            "available_for_tutoring", "available_for_employment",
            "is_documents_validated", "preregistration_code_submitted",
        ]

    def get_preregistration_code_submitted(self, obj):
        return obj.preregistration_code_id is not None

    def validate(self, attrs):
        # Un enseignant non encore accrédité (formation présentielle validée
        # par un administrateur) ne peut pas se rendre visible sur le marché
        # de l'emploi ou des cours particuliers — ça reviendrait à vendre une
        # accréditation Xporadia qu'il n'a pas encore obtenue.
        wants_tutoring = attrs.get("available_for_tutoring")
        wants_employment = attrs.get("available_for_employment")
        if wants_tutoring or wants_employment:
            user = self.instance.user if self.instance else None
            if user and not user.is_documents_validated:
                raise serializers.ValidationError(
                    "Votre compte doit d'abord être validé par Xporadia (formation présentielle "
                    "et code de préinscription) avant d'être visible pour le recrutement ou les "
                    "cours particuliers."
                )
        return attrs


class SubmitPreRegistrationCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=12)

    def validate_code(self, value):
        code = value.strip().upper()
        try:
            preregistration_code = PreRegistrationCode.objects.get(code=code)
        except PreRegistrationCode.DoesNotExist:
            raise serializers.ValidationError("Ce code de préinscription est introuvable.")
        if preregistration_code.is_used:
            raise serializers.ValidationError("Ce code de préinscription a déjà été utilisé.")
        self.context["preregistration_code"] = preregistration_code
        return code

    def save(self):
        user = self.context["request"].user
        preregistration_code = self.context["preregistration_code"]
        preregistration_code.is_used = True
        preregistration_code.used_by = user
        preregistration_code.used_at = timezone.now()
        preregistration_code.save(update_fields=["is_used", "used_by", "used_at"])
        user.teacher_profile.preregistration_code = preregistration_code
        user.teacher_profile.save(update_fields=["preregistration_code"])
        return preregistration_code


class DirectorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DirectorProfile
        fields = [
            "school_name", "address", "levels_taught", "student_count", "is_partner",
        ]
        read_only_fields = ["is_partner"]


class CompanyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyProfile
        fields = ["company_name", "sector", "address", "is_partner"]
        read_only_fields = ["is_partner"]


def _current_certification_level(user):
    from apps.certification.models import Certification, CertificationLevel

    levels_achieved = set(
        Certification.objects.filter(teacher=user, is_valid=True).values_list("level", flat=True)
    )
    for level in [CertificationLevel.GOLD, CertificationLevel.SILVER, CertificationLevel.BRONZE]:
        if level in levels_achieved:
            return level
    return None


class TeacherDirectoryCardSerializer(serializers.ModelSerializer):
    """Vue d'un profil enseignant par un enseignant tiers (annuaire).

    Reflète la matrice de visibilité du cahier des charges pour le rôle
    Enseignant : nom, photo, matières, niveau de certification et
    disponibilités sont visibles ; le tarif horaire des cours particuliers
    ne l'est pas (réservé au parent), ni l'email/téléphone (réservés à
    l'admin).
    """

    id = serializers.IntegerField(source="user.id", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    avatar = serializers.ImageField(source="user.avatar", read_only=True)
    current_level = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = [
            "id", "first_name", "last_name", "avatar", "subjects", "experience_years",
            "location", "available_for_tutoring", "available_for_employment", "current_level",
        ]
        read_only_fields = fields

    def get_current_level(self, obj):
        return _current_certification_level(obj.user)


class TeacherDirectoryDetailSerializer(TeacherDirectoryCardSerializer):
    certifications = serializers.SerializerMethodField()

    class Meta(TeacherDirectoryCardSerializer.Meta):
        fields = TeacherDirectoryCardSerializer.Meta.fields + ["bio", "certifications"]
        read_only_fields = fields

    def get_certifications(self, obj):
        from apps.certification.models import Certification
        from apps.certification.serializers import CertificationSerializer

        qs = (
            Certification.objects.filter(teacher=obj.user, is_valid=True)
            .select_related("module")
            .order_by("-issued_at")
        )
        return CertificationSerializer(qs, many=True).data


class TeacherTutoringCardSerializer(TeacherDirectoryCardSerializer):
    """Vue d'un profil enseignant par un PARENT — seul rôle pour lequel le
    tarif horaire des cours particuliers est révélé (voir le docstring de
    TeacherDirectoryCardSerializer sur la matrice de visibilité)."""

    class Meta(TeacherDirectoryCardSerializer.Meta):
        fields = TeacherDirectoryCardSerializer.Meta.fields + ["hourly_rate"]
        read_only_fields = fields


class TeacherTutoringDetailSerializer(TeacherTutoringCardSerializer):
    bio = serializers.CharField(read_only=True)
    certifications = serializers.SerializerMethodField()

    class Meta(TeacherTutoringCardSerializer.Meta):
        fields = TeacherTutoringCardSerializer.Meta.fields + ["bio", "certifications"]
        read_only_fields = fields

    def get_certifications(self, obj):
        from apps.certification.models import Certification
        from apps.certification.serializers import CertificationSerializer

        qs = (
            Certification.objects.filter(teacher=obj.user, is_valid=True)
            .select_related("module")
            .order_by("-issued_at")
        )
        return CertificationSerializer(qs, many=True).data


class EstablishmentDirectoryCardSerializer(serializers.ModelSerializer):
    """Vue publique d'un établissement — alimente le fil d'actualité au même
    titre que les enseignants."""

    id = serializers.IntegerField(source="user.id", read_only=True)
    avatar = serializers.ImageField(source="user.avatar", read_only=True)

    class Meta:
        model = DirectorProfile
        fields = ["id", "school_name", "address", "levels_taught", "student_count", "is_partner", "avatar"]
        read_only_fields = fields


class EstablishmentDirectoryDetailSerializer(EstablishmentDirectoryCardSerializer):
    departments = serializers.SerializerMethodField()

    class Meta(EstablishmentDirectoryCardSerializer.Meta):
        fields = EstablishmentDirectoryCardSerializer.Meta.fields + ["departments"]
        read_only_fields = fields

    def get_departments(self, obj):
        from apps.academics.models import Department
        from apps.academics.serializers import DepartmentSerializer

        qs = Department.objects.filter(establishment=obj)
        return DepartmentSerializer(qs, many=True).data


class TeacherCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = TeacherComment
        fields = ["id", "body", "is_anonymous", "author_name", "created_at"]
        read_only_fields = fields

    def get_author_name(self, obj):
        return "Anonyme" if obj.is_anonymous else obj.author.get_full_name()


class CreateTeacherCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherComment
        fields = ["body", "is_anonymous"]

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Le commentaire ne peut pas être vide.")
        return value.strip()


class ChildDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Child
        fields = ["id", "first_name", "class_level", "target_subjects"]


class ParentProfileSerializer(serializers.ModelSerializer):
    children = ChildDetailSerializer(many=True, read_only=True)

    class Meta:
        model = ParentProfile
        fields = ["location", "subscription_active", "children"]
        read_only_fields = ["subscription_active"]


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class VerifyOTPSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6, min_length=6)


class UpdateMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name", "last_name", "phone", "avatar",
            "profile_visible", "notify_email", "notify_sms", "notify_push",
            "two_fa_enabled",
        ]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Mot de passe actuel incorrect.")
        return value


class AccountDeletionRequestSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Mot de passe incorrect.")
        return value
