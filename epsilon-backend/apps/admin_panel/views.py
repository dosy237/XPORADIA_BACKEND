from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import NotificationType
from apps.notifications.services import notify_user
from apps.users.models import User, UserRole

from .serializers import AdminUserListSerializer, PendingAccreditationSerializer


def _require_admin(user):
    if not user.has_role(UserRole.ADMIN):
        raise PermissionDenied("Réservé aux administrateurs.")


class DashboardStatsView(APIView):
    """Grands chiffres pour l'accueil de l'espace admin mobile — jamais
    de détail lourd ici, juste de quoi savoir s'il y a quelque chose à
    traiter (voir les écrans dédiés pour le détail)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        _require_admin(request.user)

        from apps.library.models import LibraryResource, ModerationStatus
        from apps.payments.models import Dispute, DisputeStatus, Payment, PaymentStatus

        today = timezone.localdate()
        pending_accreditation = User.objects.filter(
            is_documents_validated=False, primary_role__in=[UserRole.TEACHER, UserRole.DIRECTOR],
        ).count()
        pending_library = LibraryResource.objects.filter(moderation_status=ModerationStatus.PENDING).count()
        open_disputes = Dispute.objects.filter(status__in=[DisputeStatus.OPEN, DisputeStatus.REVIEWED]).count()
        today_payments_total = (
            Payment.objects.filter(status=PaymentStatus.COMPLETED, completed_at__date=today)
            .aggregate(total=Sum("amount"))["total"]
            or 0
        )

        return Response({
            "pending_accreditation": pending_accreditation,
            "pending_library": pending_library,
            "open_disputes": open_disputes,
            "today_payments_total": today_payments_total,
        })


class PendingAccreditationView(generics.ListAPIView):
    """Comptes enseignant/directeur en attente de validation de formation
    présentielle — même geste que l'action Django Admin existante, mais
    accessible depuis le mobile pour un traitement rapide au jour le jour."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PendingAccreditationSerializer
    pagination_class = None

    def get_queryset(self):
        _require_admin(self.request.user)
        return User.objects.filter(
            is_documents_validated=False, primary_role__in=[UserRole.TEACHER, UserRole.DIRECTOR],
        ).order_by("created_at")


class ValidateAccreditationView(APIView):
    """Validation d'un compte — identique à l'action Django Admin
    validate_selected_accounts, réutilisée pour ne jamais dupliquer la
    logique de notification."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        _require_admin(request.user)
        target = get_object_or_404(User, pk=user_id, is_documents_validated=False)
        target.is_documents_validated = True
        target.save(update_fields=["is_documents_validated"])
        notify_user(
            target, NotificationType.SYSTEM,
            title="Votre compte Xporadia est validé",
            body=(
                "Xporadia a validé votre formation présentielle et votre profil. "
                "Vous êtes désormais officiellement accrédité sur la plateforme."
            ),
        )
        return Response({"id": target.id, "is_documents_validated": True})


class PendingLibraryResourcesView(generics.ListAPIView):
    """File de modération bibliothèque, TOUS établissements confondus —
    contrairement à la vue établissement (réservée au directeur de CET
    établissement), celle-ci donne une vue globale à l'administrateur."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        _require_admin(request.user)

        from apps.library.models import LibraryResource, ModerationStatus
        from apps.library.serializers import LibraryResourceSerializer

        qs = LibraryResource.objects.filter(
            moderation_status=ModerationStatus.PENDING
        ).select_related("author", "establishment").order_by("created_at")
        data = LibraryResourceSerializer(qs, many=True, context={"request": request}).data
        # Ajoute le nom de l'établissement, absent du serializer de base
        # (pensé pour un contexte où l'établissement est déjà implicite).
        for item, resource in zip(data, qs):
            item["establishment_name"] = resource.establishment.school_name
        return Response(data)


class ModerateLibraryResourceView(APIView):
    """Approbation ou rejet d'une ressource en attente."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, resource_id):
        _require_admin(request.user)

        from apps.library.models import LibraryResource, ModerationStatus

        resource = get_object_or_404(LibraryResource, pk=resource_id, moderation_status=ModerationStatus.PENDING)
        approve = request.data.get("approve", True)
        resource.moderation_status = ModerationStatus.APPROVED if approve else ModerationStatus.REJECTED
        resource.save(update_fields=["moderation_status"])

        if resource.author_id:
            notify_user(
                resource.author, NotificationType.SYSTEM,
                title="Ressource " + ("approuvée" if approve else "rejetée"),
                body=f"Votre contribution « {resource.title} » a été "
                     + ("approuvée et publiée." if approve else "rejetée."),
            )
        return Response({"id": resource.id, "moderation_status": resource.moderation_status})


class TogglePartnerStatusView(APIView):
    """Statut "Partenaire" d'un établissement ou d'une entreprise —
    aujourd'hui un simple bouton administrateur (le calcul automatique du
    label, prévu par le cahier des charges sur un ratio de recrutement,
    relève du chantier Administration plus large, pas de ce premier
    Niveau 1)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        _require_admin(request.user)
        target = get_object_or_404(User, pk=user_id)

        if target.has_role(UserRole.DIRECTOR):
            profile = target.director_profile
        elif target.has_role(UserRole.COMPANY):
            profile = target.company_profile
        else:
            raise PermissionDenied("Le statut partenaire ne concerne que les établissements et entreprises.")

        profile.is_partner = not profile.is_partner
        profile.save(update_fields=["is_partner"])
        notify_user(
            target, NotificationType.SYSTEM,
            title="Statut partenaire Xporadia",
            body=(
                "Votre établissement est désormais Partenaire Xporadia."
                if profile.is_partner
                else "Votre statut de partenaire Xporadia a été retiré."
            ),
        )
        return Response({"id": target.id, "is_partner": profile.is_partner})


class ToggleProfileVisibilityView(APIView):
    """Masquage d'un profil enseignant de l'annuaire public — modération,
    sans jamais désactiver le compte lui-même (l'enseignant garde accès à
    tout le reste de la plateforme)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        _require_admin(request.user)
        target = get_object_or_404(User, pk=user_id, primary_role=UserRole.TEACHER)
        target.profile_visible = not target.profile_visible
        target.save(update_fields=["profile_visible"])

        if not target.profile_visible:
            notify_user(
                target, NotificationType.SYSTEM,
                title="Profil masqué de l'annuaire",
                body="Votre profil public a été temporairement masqué par un administrateur. "
                     "Contactez le support pour en savoir plus.",
            )
        return Response({"id": target.id, "profile_visible": target.profile_visible})


class AdminUserListView(generics.ListAPIView):
    """Recherche/liste d'utilisateurs par rôle — réutilisée pour les 4
    catégories gérées côté admin (élève, enseignant, établissement,
    entreprise) plutôt que 4 vues quasi identiques."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminUserListSerializer
    pagination_class = None

    def get_queryset(self):
        _require_admin(self.request.user)
        role = self.request.query_params.get("role")
        if role not in (UserRole.STUDENT, UserRole.TEACHER, UserRole.DIRECTOR, UserRole.COMPANY):
            raise ValidationError({"role": "Doit être student, teacher, director ou company."})
        qs = User.objects.filter(primary_role=role).order_by("first_name", "last_name")
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search)
            )
        return qs


class AdminUserDetailView(APIView):
    """Fiche complète d'un utilisateur — informations propres au rôle
    (établissement/classe pour un élève, matières pour un enseignant...),
    jamais un simple echo du modèle User brut."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        _require_admin(request.user)
        user = get_object_or_404(User, pk=user_id)
        data = AdminUserListSerializer(user, context={"request": request}).data

        if user.has_role(UserRole.STUDENT):
            child = getattr(user, "child_profile", None)
            if child:
                from apps.academics.models import Enrollment, EnrollmentStatus

                enrollment = Enrollment.objects.filter(
                    child=child, status=EnrollmentStatus.ACTIVE
                ).select_related("school_class__track__department__establishment").first()
                data["role_detail"] = {
                    "declared_level": child.class_level,
                    "has_parent": child.parent_id is not None,
                    "school_class": str(enrollment.school_class) if enrollment else None,
                    "establishment": (
                        enrollment.school_class.track.department.establishment.school_name
                        if enrollment else None
                    ),
                }
        elif user.has_role(UserRole.TEACHER):
            profile = getattr(user, "teacher_profile", None)
            from apps.certification.models import Certification

            certifications = Certification.objects.filter(teacher=user).select_related("module").order_by("-issued_at")
            data["role_detail"] = {
                "subjects": profile.subjects if profile else [],
                "is_documents_validated": user.is_documents_validated,
                "profile_visible": user.profile_visible,
            } if profile else {}
            data["certifications"] = [
                {
                    "id": str(c.id), "module_title": c.module.title, "level": c.level,
                    "score_total": str(c.score_total), "is_valid": c.is_valid,
                    "issued_at": c.issued_at, "revoked_at": c.revoked_at,
                }
                for c in certifications
            ]
        elif user.has_role(UserRole.DIRECTOR):
            profile = getattr(user, "director_profile", None)
            data["role_detail"] = {
                "school_name": profile.school_name if profile else None,
                "is_partner": profile.is_partner if profile else None,
            }
        elif user.has_role(UserRole.COMPANY):
            profile = getattr(user, "company_profile", None)
            data["role_detail"] = {
                "company_name": profile.company_name if profile else None,
                "is_partner": profile.is_partner if profile else None,
            }

        return Response(data)


class SuspendUserView(APIView):
    """Suspension RÉVERSIBLE par un administrateur — distincte de
    l'auto-suppression RGPD (qui anonymise définitivement). Ici, aucune
    donnée n'est touchée, seul l'accès est coupé, réactivable à tout
    moment."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        _require_admin(request.user)
        target = get_object_or_404(User, pk=user_id, is_active=True)
        if target.has_role(UserRole.ADMIN):
            raise PermissionDenied("Un compte administrateur ne peut pas être suspendu depuis cet écran.")
        target.is_active = False
        target.save(update_fields=["is_active"])
        return Response({"id": target.id, "is_active": False})


class ReactivateUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        _require_admin(request.user)
        target = get_object_or_404(User, pk=user_id, is_active=False)
        target.is_active = True
        target.save(update_fields=["is_active"])
        return Response({"id": target.id, "is_active": True})


class RevokeCertificationView(APIView):
    """Révocation d'une certification — la seule façon dont is_valid
    change après émission (cahier des charges). is_valid et revoked_at
    sont TOUJOURS mis à jour ensemble, jamais l'un sans l'autre (contrairement
    à une édition brute dans Django Admin qui laisserait revoked_at nul)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, certification_id):
        _require_admin(request.user)

        from apps.certification.models import Certification

        cert = get_object_or_404(Certification, pk=certification_id, is_valid=True)
        cert.is_valid = False
        cert.revoked_at = timezone.now()
        cert.save(update_fields=["is_valid", "revoked_at"])

        notify_user(
            cert.teacher, NotificationType.SYSTEM,
            title="Certification révoquée",
            body=f"Votre certification « {cert.module.title} » a été révoquée par l'administration.",
        )
        return Response({"id": str(cert.id), "is_valid": False, "revoked_at": cert.revoked_at})


class ReinstateCertificationView(APIView):
    """Annulation d'une révocation — même principe réversible que
    suspendre/réactiver un compte."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, certification_id):
        _require_admin(request.user)

        from apps.certification.models import Certification

        cert = get_object_or_404(Certification, pk=certification_id, is_valid=False)
        cert.is_valid = True
        cert.revoked_at = None
        cert.save(update_fields=["is_valid", "revoked_at"])

        notify_user(
            cert.teacher, NotificationType.SYSTEM,
            title="Certification rétablie",
            body=f"Votre certification « {cert.module.title} » a été rétablie.",
        )
        return Response({"id": str(cert.id), "is_valid": True, "revoked_at": None})
