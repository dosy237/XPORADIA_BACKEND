from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Child, CompanyProfile, DirectorProfile, ParentProfile, TeacherProfile, User, UserRole


class UserSerializer(serializers.ModelSerializer):
    all_roles = serializers.ListField(source="get_all_roles", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "phone", "first_name", "last_name", "avatar",
            "primary_role", "secondary_roles", "all_roles",
            "is_verified", "is_documents_validated", "two_fa_enabled", "created_at",
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
    class Meta:
        model = TeacherProfile
        fields = [
            "subjects", "experience_years", "hourly_rate", "location", "bio",
            "available_for_tutoring", "available_for_employment",
        ]


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
