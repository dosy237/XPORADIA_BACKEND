from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import Child, CompanyProfile, DirectorProfile, OTPPurpose, ParentProfile, TeacherProfile, UserRole
from .serializers import (
    AccountDeletionRequestSerializer,
    ChangePasswordSerializer,
    ChildDetailSerializer,
    CompanyProfileSerializer,
    CustomTokenObtainPairSerializer,
    DirectorProfileSerializer,
    ParentProfileSerializer,
    RegisterCompanySerializer,
    RegisterDirectorSerializer,
    RegisterParentSerializer,
    RegisterTeacherSerializer,
    TeacherProfileSerializer,
    UpdateMeSerializer,
    UserSerializer,
    VerifyOTPSerializer,
)
from .services import generate_otp, verify_otp

MAX_CHILDREN_PER_PARENT = 5


class BaseRegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = None

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        # User + profil créés atomiquement : un échec sur le profil (ex. erreur
        # DB) ne doit jamais laisser un compte orphelin sans profil associé.
        with transaction.atomic():
            user = serializer.create()
        generate_otp(user, purpose=OTPPurpose.ACCOUNT_VERIFICATION)
        return Response(
            {
                "user": UserSerializer(user).data,
                "detail": "Compte créé. Un code de vérification a été envoyé.",
            },
            status=status.HTTP_201_CREATED,
        )


class RegisterTeacherView(BaseRegisterView):
    serializer_class = RegisterTeacherSerializer


class RegisterDirectorView(BaseRegisterView):
    serializer_class = RegisterDirectorSerializer


class RegisterParentView(BaseRegisterView):
    serializer_class = RegisterParentSerializer


class RegisterCompanyView(BaseRegisterView):
    serializer_class = RegisterCompanySerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]
    serializer_class = CustomTokenObtainPairSerializer


class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]


class VerifyOTPView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ok = verify_otp(request.user, serializer.validated_data["code"])
        if not ok:
            return Response(
                {"detail": "Code invalide ou expiré."}, status=status.HTTP_400_BAD_REQUEST
            )
        request.user.is_verified = True
        request.user.save(update_fields=["is_verified"])
        return Response({"detail": "Compte vérifié.", "user": UserSerializer(request.user).data})


class ResendOTPView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        generate_otp(request.user, purpose=OTPPurpose.ACCOUNT_VERIFICATION)
        return Response({"detail": "Un nouveau code a été envoyé."})


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return UpdateMeSerializer
        return UserSerializer


class TeacherProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TeacherProfileSerializer

    def get_object(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return TeacherProfile.objects.get(user=self.request.user)


class DirectorProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DirectorProfileSerializer

    def get_object(self):
        if not self.request.user.has_role(UserRole.DIRECTOR):
            raise PermissionDenied("Réservé aux directeurs d'établissement.")
        return DirectorProfile.objects.get(user=self.request.user)


class CompanyProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CompanyProfileSerializer

    def get_object(self):
        if not self.request.user.has_role(UserRole.COMPANY):
            raise PermissionDenied("Réservé aux entreprises.")
        return CompanyProfile.objects.get(user=self.request.user)


class ParentProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ParentProfileSerializer

    def get_object(self):
        if not self.request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")
        return ParentProfile.objects.get(user=self.request.user)


class ChildListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChildDetailSerializer
    pagination_class = None  # au plus 5 enfants par parent : pas de pagination nécessaire

    def get_parent_profile(self):
        if not self.request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")
        return ParentProfile.objects.get(user=self.request.user)

    def get_queryset(self):
        return Child.objects.filter(parent=self.get_parent_profile())

    def perform_create(self, serializer):
        parent_profile = self.get_parent_profile()
        if parent_profile.children.count() >= MAX_CHILDREN_PER_PARENT:
            raise ValidationError("Maximum 5 enfants par parent.")
        serializer.save(parent=parent_profile)


class ChildDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChildDetailSerializer

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")
        return Child.objects.filter(parent__user=self.request.user)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Mot de passe mis à jour."})


ROLE_PROFILE_SERIALIZERS = {
    UserRole.TEACHER: (TeacherProfile, TeacherProfileSerializer),
    UserRole.DIRECTOR: (DirectorProfile, DirectorProfileSerializer),
    UserRole.COMPANY: (CompanyProfile, CompanyProfileSerializer),
    UserRole.PARENT: (ParentProfile, ParentProfileSerializer),
}


class MyDataExportView(APIView):
    """Droit d'accès RGPD : export intégral des données personnelles de
    l'utilisateur connecté (compte + profil de rôle), au format JSON."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        data = {
            "account": UserSerializer(user).data,
            "profiles": {},
        }
        for role in user.get_all_roles():
            mapping = ROLE_PROFILE_SERIALIZERS.get(role)
            if not mapping:
                continue
            model, serializer_class = mapping
            instance = model.objects.filter(user=user).first()
            if instance:
                data["profiles"][role] = serializer_class(instance).data
        response = Response(data)
        response["Content-Disposition"] = 'attachment; filename="xporadia-mes-donnees.json"'
        return response


class AccountDeletionRequestView(APIView):
    """Droit à l'effacement RGPD : anonymise les données personnelles et
    désactive le compte. Les données non-personnelles liées (certifications,
    recrutements...) sont conservées pour l'intégrité de l'historique, comme
    l'exige la traçabilité légale — seules les données identifiantes sont
    effacées."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AccountDeletionRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.email = f"compte-supprime-{user.id}@xporadia.invalid"
        user.first_name = "Compte"
        user.last_name = "Supprimé"
        user.phone = ""
        user.avatar = None
        user.is_active = False
        user.deletion_requested_at = timezone.now()
        user.set_unusable_password()
        user.save()
        return Response({"detail": "Compte anonymisé et désactivé."})
