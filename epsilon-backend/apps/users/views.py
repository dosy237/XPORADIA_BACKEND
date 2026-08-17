from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import (
    Child,
    ChildClaimRequest,
    ChildClaimRequestStatus,
    CompanyProfile,
    DirectorProfile,
    OTPPurpose,
    ParentProfile,
    StudentActivationInvite,
    TeacherComment,
    TeacherProfile,
    User,
    UserRole,
)
from .serializers import (
    AccountDeletionRequestSerializer,
    ChangePasswordSerializer,
    ChildDetailSerializer,
    ChildClaimRequestSerializer,
    CompanyDirectoryCardSerializer,
    CompanyDirectoryDetailSerializer,
    CompanyProfileSerializer,
    CreateTeacherCommentSerializer,
    CustomTokenObtainPairSerializer,
    DirectorProfileSerializer,
    EstablishmentDirectoryCardSerializer,
    EstablishmentDirectoryDetailSerializer,
    ParentProfileSerializer,
    RegisterCompanySerializer,
    RegisterDirectorSerializer,
    RegisterParentSerializer,
    RegisterStudentSerializer,
    RegisterTeacherSerializer,
    StudentActivationPreviewSerializer,
    StudentActivationSerializer,
    SubmitPreRegistrationCodeSerializer,
    TeacherCommentSerializer,
    TeacherDirectoryCardSerializer,
    TeacherDirectoryDetailSerializer,
    TeacherProfileSerializer,
    TeacherTutoringCardSerializer,
    TeacherTutoringDetailSerializer,
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


class RegisterStudentView(APIView):
    """Inscription directe élève — vue dédiée plutôt que BaseRegisterView
    générique, car RegisterStudentSerializer.create() renvoie (user, child)
    et non un simple user (le frontend a besoin de child_id tout de suite
    pour enchaîner sur la déclaration d'établissement)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user, child = serializer.create()
        generate_otp(user, purpose=OTPPurpose.ACCOUNT_VERIFICATION)
        return Response(
            {
                "user": UserSerializer(user).data,
                "child_id": child.id,
                "detail": "Compte créé. Un code de vérification a été envoyé.",
            },
            status=status.HTTP_201_CREATED,
        )


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


class MyAvatarView(APIView):
    """Photo de profil — tous rôles. Endpoint dédié plutôt que de passer
    par MeView : le recadrage se fait déjà côté app (sélecteur natif),
    ici on ne fait que stocker le fichier reçu ou l'effacer."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"avatar": "Fichier requis."}, status=status.HTTP_400_BAD_REQUEST)
        request.user.avatar = avatar
        request.user.save(update_fields=["avatar"])
        return Response(UserSerializer(request.user, context={"request": request}).data)

    def delete(self, request):
        request.user.avatar = None
        request.user.save(update_fields=["avatar"])
        return Response(UserSerializer(request.user, context={"request": request}).data)


class TeacherProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TeacherProfileSerializer

    def get_object(self):
        if not self.request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        return TeacherProfile.objects.get(user=self.request.user)


class SubmitPreRegistrationCodeView(APIView):
    """L'enseignant renseigne le code obtenu après sa formation présentielle.

    La soumission ne valide pas le compte automatiquement : elle place le
    dossier en attente de revue par un administrateur (garde-fou contre les
    erreurs de saisie/fraude), qui valide ensuite via l'admin Django.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.has_role(UserRole.TEACHER):
            raise PermissionDenied("Réservé aux enseignants.")
        serializer = SubmitPreRegistrationCodeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": "Code enregistré. Votre compte est en attente de validation par Xporadia."}
        )


def _send_student_invitation_email(invite):
    from django.conf import settings
    from django.core.mail import send_mail

    invite_link = f"{settings.INVITE_LINK_BASE}/invite/student/{invite.token}"
    send_mail(
        subject="Votre espace élève Xporadia",
        message=(
            f"Bonjour {invite.child.first_name},\n\n"
            "Votre établissement vous a créé un accès personnel à Xporadia : vous pourrez y "
            "suivre vos devoirs, échanger avec vos enseignants et accéder à la bibliothèque de "
            "votre école, avec votre propre compte plutôt que celui de vos parents.\n\n"
            f"Rejoignez votre salle de classe ici : {invite_link}\n\n"
            "Ce lien est personnel, ne le partagez avec personne."
        ),
        from_email=None,
        recipient_list=[invite.email],
        fail_silently=True,
    )


class StudentInviteCreateView(APIView):
    """Le directeur déclenche l'invitation d'activation pour un élève déjà
    inscrit (Enrollment) dans une de ses classes — la création de la fiche
    ENFANT elle-même reste, pour l'instant, du ressort du parent à
    l'inscription (voir RegisterParentSerializer) ; ce que cette vue permet,
    c'est de transformer une fiche déjà enrôlée en compte élève autonome.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.academics.models import Enrollment

        if not request.user.has_role(UserRole.DIRECTOR):
            raise PermissionDenied("Réservé aux directeurs d'établissement.")

        child_id = request.data.get("child_id")
        email = request.data.get("email", "").strip().lower()
        if not child_id or not email:
            raise ValidationError({"detail": "child_id et email sont requis."})

        child = get_object_or_404(Child, pk=child_id)
        if child.user_id:
            raise ValidationError({"detail": "Cet élève a déjà un compte actif."})

        establishment_ids = {request.user.director_profile.id}
        enrollment = (
            Enrollment.objects.filter(child=child, school_class__track__department__establishment_id__in=establishment_ids)
            .select_related("school_class")
            .first()
        )
        if not enrollment:
            raise PermissionDenied("Cet élève n'est pas inscrit dans une classe de votre établissement.")

        invite = StudentActivationInvite.objects.create(child=child, email=email, invited_by=request.user)
        _send_student_invitation_email(invite)

        return Response(
            {"detail": f"Invitation envoyée à {email}."}, status=status.HTTP_201_CREATED
        )


class StudentActivationPreviewView(APIView):
    """Aperçu public (non authentifié) affiché avant que l'élève choisisse
    son mot de passe — /invite/student/<token>."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        invite = get_object_or_404(StudentActivationInvite.objects.select_related("child"), token=token)
        if invite.is_accepted:
            return Response({"detail": "Ce compte élève a déjà été activé."}, status=status.HTTP_410_GONE)

        from apps.academics.models import Enrollment

        enrollment = (
            Enrollment.objects.filter(child=invite.child)
            .select_related("school_class__track__department__establishment")
            .order_by("-enrolled_at")
            .first()
        )
        school_name = (
            enrollment.school_class.track.department.establishment.school_name if enrollment else None
        )
        data = StudentActivationPreviewSerializer(
            {
                "first_name": invite.child.first_name,
                "last_name": invite.child.last_name,
                "class_level": invite.child.class_level,
                "school_name": school_name,
                "email": invite.email,
            }
        ).data
        return Response(data)


class StudentActivationView(APIView):
    """L'élève choisit son mot de passe et active son compte — crée le
    User STUDENT, le relie à sa fiche ENFANT, et informe le parent par
    transparence (pas un blocage, une notification)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from django.utils import timezone

        from apps.notifications.models import NotificationType
        from apps.notifications.services import notify_user

        serializer = StudentActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user, child = serializer.create()

        invite = child.activation_invites.filter(is_accepted=True).order_by("-accepted_at").first()
        if invite:
            invite.parent_notified_at = timezone.now()
            invite.save(update_fields=["parent_notified_at"])

        if child.parent_id:
            notify_user(
                child.parent.user,
                NotificationType.SYSTEM,
                title=f"{child.first_name} a activé son espace élève",
                body=(
                    f"{child.first_name} dispose désormais de son propre compte Xporadia pour suivre "
                    "ses cours, ses devoirs et échanger avec ses enseignants."
                ),
                data={"child_id": child.id},
            )

        from apps.messaging.services import ensure_student_messaging

        ensure_student_messaging(child)

        return Response(
            {"user": UserSerializer(user).data, "detail": "Compte élève activé."},
            status=status.HTTP_201_CREATED,
        )


class TeacherDirectoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Annuaire des enseignants — alimente le fil public (onglet Fil
    d'actualité) : accessible aux visiteurs non connectés comme aux
    utilisateurs authentifiés, quel que soit leur rôle. Le tarif horaire et
    les coordonnées restent masqués (réservés à la vue parent/admin, story
    dédiée future)."""

    permission_classes = [permissions.AllowAny]
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    def get_queryset(self):
        qs = (
            TeacherProfile.objects.filter(
                user__is_active=True,
                # Enseignant pas encore accrédité par Xporadia (formation présentielle
                # + code de préinscription validés par un administrateur) : son
                # profil n'apparaît pas encore dans l'annuaire.
                user__is_documents_validated=True,
            )
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
        )
        # Un profil masqué par modération reste néanmoins consultable par
        # le personnel (is_staff) — sinon personne, pas même
        # l'administrateur qui l'a masqué, ne pourrait jamais le
        # réafficher : la fiche serait tout simplement introuvable.
        if not self.request.user.is_staff:
            qs = qs.filter(user__profile_visible=True)
        if self.request.user.is_authenticated:
            qs = qs.exclude(user=self.request.user)
        subject = self.request.query_params.get("subject")
        if subject:
            # Filtrage en Python : JSONField.__contains n'est pas supporté sur
            # SQLite (dev). À revisiter avec un index de recherche dédié si
            # l'annuaire grossit significativement en production (Postgres).
            needle = subject.lower()
            matching_ids = [tp.pk for tp in qs if any(needle in s.lower() for s in tp.subjects)]
            qs = qs.filter(pk__in=matching_ids)
        if self.request.query_params.get("available_for_tutoring") == "true":
            qs = qs.filter(available_for_tutoring=True)
        location = self.request.query_params.get("location")
        if location:
            # Filtrage textuel sur la commune/quartier déclaré (ex. "Cocody") —
            # une recherche géolocalisée par rayon GPS nécessiterait un
            # fournisseur de géocodage (Google Maps/Mapbox) non configuré
            # dans cet environnement ; ce filtre couvre le besoin réel du
            # parent ("un enseignant près de chez moi") sans dépendance externe.
            qs = qs.filter(location__icontains=location)
        return qs

    def get_serializer_class(self):
        # Le tarif horaire des cours particuliers n'est révélé qu'au parent
        # qui cherche un enseignant pour ses enfants (EP-05) — voir le
        # docstring de TeacherTutoringCardSerializer.
        is_parent = self.request.user.is_authenticated and self.request.user.has_role(UserRole.PARENT)
        if self.action == "retrieve":
            return TeacherTutoringDetailSerializer if is_parent else TeacherDirectoryDetailSerializer
        return TeacherTutoringCardSerializer if is_parent else TeacherDirectoryCardSerializer


class EstablishmentDirectoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Annuaire public des établissements — alimente le fil d'actualité au
    même titre que l'annuaire des enseignants."""

    permission_classes = [permissions.AllowAny]
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    def get_queryset(self):
        qs = (
            DirectorProfile.objects.filter(
                user__is_active=True,
                user__profile_visible=True,
                user__is_documents_validated=True,
            )
            .select_related("user")
            .order_by("school_name")
        )
        location = self.request.query_params.get("location")
        if location:
            qs = qs.filter(address__icontains=location)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(school_name__icontains=search)
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return EstablishmentDirectoryDetailSerializer
        return EstablishmentDirectoryCardSerializer


class CompanyDirectoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Annuaire public des entreprises partenaires — symétrique à
    l'annuaire établissements, pour la page Annuaire générale."""

    permission_classes = [permissions.AllowAny]
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    def get_queryset(self):
        qs = (
            CompanyProfile.objects.filter(
                user__is_active=True,
                user__profile_visible=True,
                user__is_documents_validated=True,
            )
            .select_related("user")
            .order_by("company_name")
        )
        sector = self.request.query_params.get("sector")
        if sector:
            qs = qs.filter(sector__icontains=sector)
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CompanyDirectoryDetailSerializer
        return CompanyDirectoryCardSerializer


class TeacherCommentListCreateView(generics.ListCreateAPIView):
    pagination_class = None

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get_teacher(self):
        try:
            teacher = User.objects.get(id=self.kwargs["user_id"])
        except User.DoesNotExist:
            raise Http404
        if not teacher.has_role(UserRole.TEACHER):
            raise Http404
        return teacher

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreateTeacherCommentSerializer
        return TeacherCommentSerializer

    def get_queryset(self):
        teacher = self.get_teacher()
        return TeacherComment.objects.filter(teacher=teacher, is_hidden=False).select_related("author")

    def perform_create(self, serializer):
        teacher = self.get_teacher()
        if teacher == self.request.user:
            raise ValidationError("Vous ne pouvez pas commenter votre propre profil.")
        serializer.save(teacher=teacher, author=self.request.user)


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


class SearchUnclaimedChildView(APIView):
    """Recherche d'un enfant auto-inscrit à réclamer — uniquement par
    email de l'ENFANT lui-même (pas de nom, pour éviter toute pêche aux
    informations), et uniquement s'il n'est PAS déjà rattaché à un
    parent : ne révèle jamais qu'un enfant appartient déjà à quelqu'un
    d'autre."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")
        email = request.query_params.get("child_email", "").strip().lower()
        if not email:
            return Response({"child": None})
        try:
            child = Child.objects.select_related("user").get(user__email__iexact=email, parent__isnull=True)
        except Child.DoesNotExist:
            return Response({"child": None})
        return Response({"child": {"id": child.id, "first_name": child.first_name, "last_name": child.last_name,
                          "class_level": child.class_level}})


class CreateChildClaimRequestView(APIView):
    """Le parent soumet sa demande — jamais de rattachement immédiat,
    l'enfant doit approuver."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")
        parent_profile = ParentProfile.objects.get(user=request.user)
        child_id = request.data.get("child_id")
        try:
            child = Child.objects.select_related("user").get(pk=child_id, parent__isnull=True)
        except Child.DoesNotExist:
            raise ValidationError({"child_id": "Cet enfant est introuvable ou déjà rattaché."})
        if ChildClaimRequest.objects.filter(
            parent=parent_profile, child=child, status=ChildClaimRequestStatus.PENDING
        ).exists():
            return Response({"detail": "Une demande est déjà en attente pour cet enfant."}, status=status.HTTP_400_BAD_REQUEST)

        claim = ChildClaimRequest.objects.create(parent=parent_profile, child=child)
        if child.user_id:
            from apps.notifications.models import NotificationType
            from apps.notifications.services import notify_user

            notify_user(
                child.user, NotificationType.ENROLLMENT_UPDATE,
                title="Demande de rattachement parent",
                body=f"{request.user.get_full_name()} indique être votre parent et souhaite suivre votre scolarité.",
                data={"claim_request_id": claim.id},
            )
        return Response({"id": claim.id, "status": claim.status}, status=status.HTTP_201_CREATED)


class MyChildClaimRequestsView(generics.ListAPIView):
    """Statut des demandes soumises par le parent connecté."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChildClaimRequestSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.PARENT):
            raise PermissionDenied("Réservé aux parents.")
        parent_profile = ParentProfile.objects.get(user=self.request.user)
        return ChildClaimRequest.objects.filter(parent=parent_profile).select_related("child")


class ChildClaimRequestsForMeView(generics.ListAPIView):
    """Demandes de rattachement reçues par l'élève connecté, à traiter."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChildClaimRequestSerializer
    pagination_class = None

    def get_queryset(self):
        child = getattr(self.request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        return ChildClaimRequest.objects.filter(
            child=child, status=ChildClaimRequestStatus.PENDING
        ).select_related("parent__user")


class ReviewChildClaimRequestView(APIView):
    """L'élève approuve ou rejette — seul geste qui rattache réellement
    Child.parent."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        child = getattr(request.user, "child_profile", None)
        if not child:
            raise PermissionDenied("Réservé aux comptes élève.")
        claim = get_object_or_404(ChildClaimRequest, pk=pk, child=child)
        if claim.status != ChildClaimRequestStatus.PENDING:
            return Response({"detail": "Cette demande a déjà été traitée."}, status=status.HTTP_400_BAD_REQUEST)

        approve = request.data.get("approve", True)
        claim.status = ChildClaimRequestStatus.APPROVED if approve else ChildClaimRequestStatus.REJECTED
        claim.reviewed_at = timezone.now()
        claim.save(update_fields=["status", "reviewed_at"])

        if approve:
            child.parent = claim.parent
            child.save(update_fields=["parent"])

        return Response({"id": claim.id, "status": claim.status})


class CreateAdminView(APIView):
    """Création d'un compte administrateur — réservée aux administrateurs
    déjà existants. Jamais accessible via l'inscription publique : c'est
    le SEUL chemin par lequel un compte "admin" peut être créé après le
    tout premier (bootstrappé via `manage.py createsuperuser`, qui fixe
    déjà primary_role=admin automatiquement). Un mot de passe temporaire
    est généré et envoyé par email — jamais renvoyé dans la réponse API,
    pour qu'il ne transite jamais que par un seul canal privé."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.has_role(UserRole.ADMIN):
            raise PermissionDenied("Réservé aux administrateurs.")

        email = request.data.get("email", "").strip().lower()
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()
        if not (email and first_name and last_name):
            raise ValidationError({"email": "Email, prénom et nom sont requis."})
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError({"email": "Un compte existe déjà avec cet email."})

        import secrets
        import string

        temp_password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
        new_admin = User.objects.create_user(
            email=email, password=temp_password, first_name=first_name, last_name=last_name,
            primary_role=UserRole.ADMIN, is_staff=True, is_verified=True, is_documents_validated=True,
        )

        from django.core.mail import send_mail

        send_mail(
            subject="Votre accès administrateur Xporadia",
            message=(
                f"Bonjour {first_name},\n\n"
                f"{request.user.get_full_name()} vous a créé un accès administrateur sur Xporadia.\n\n"
                f"Email : {email}\n"
                f"Mot de passe temporaire : {temp_password}\n\n"
                "Connectez-vous puis changez ce mot de passe dès que possible."
            ),
            from_email=None,
            recipient_list=[email],
            fail_silently=True,
        )

        return Response(
            {"id": new_admin.id, "email": new_admin.email, "detail": "Compte créé, identifiants envoyés par email."},
            status=status.HTTP_201_CREATED,
        )


class AdminListView(generics.ListAPIView):
    """Liste des administrateurs existants — pour qu'un admin sache qui
    d'autre a accès, avant d'en créer un nouveau."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer
    pagination_class = None

    def get_queryset(self):
        if not self.request.user.has_role(UserRole.ADMIN):
            raise PermissionDenied("Réservé aux administrateurs.")
        return User.objects.filter(primary_role=UserRole.ADMIN, is_active=True).order_by("first_name")
