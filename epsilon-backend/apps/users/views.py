from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import OTPPurpose, TeacherProfile, UserRole
from .serializers import (
    CustomTokenObtainPairSerializer,
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
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Réservé aux enseignants.")
        return TeacherProfile.objects.get(user=self.request.user)
