from django.db import models
from django.db.models import F
from django.http import Http404
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Enrollment, EnrollmentStatus, SchoolClass, Subject
from apps.users.models import DirectorProfile, UserRole

from .models import LibraryResource, ModerationStatus, ResourceDownload, ResourceFavorite
from .serializers import LibraryResourceSerializer


def _affiliated_establishment_ids(user):
    """Établissements où l'utilisateur est directeur, titulaire d'une
    classe, enseignant dédié d'une matière, ou élève/parent inscrit —
    donc légitime à consulter (et pour le personnel, à contribuer à) la
    bibliothèque numérique de cet établissement."""

    ids = set()
    try:
        ids.add(user.director_profile.id)
    except DirectorProfile.DoesNotExist:
        pass
    ids.update(
        SchoolClass.objects.filter(homeroom_teacher=user).values_list(
            "track__department__establishment_id", flat=True
        )
    )
    ids.update(
        Subject.objects.filter(teacher=user).values_list(
            "school_class__track__department__establishment_id", flat=True
        )
    )
    # Élève avec compte propre — accès direct à la bibliothèque de son
    # établissement, à l'intégralité du fonds (pas seulement son niveau,
    # voir Story « profil élève »).
    child = getattr(user, "child_profile", None)
    if child:
        ids.update(
            Enrollment.objects.filter(child=child, status=EnrollmentStatus.ACTIVE).values_list(
                "school_class__track__department__establishment_id", flat=True
            )
        )
    return ids


def _get_establishment(establishment_id):
    try:
        return DirectorProfile.objects.get(id=establishment_id)
    except DirectorProfile.DoesNotExist:
        raise Http404


def _require_establishment_access(establishment, user):
    if establishment.id not in _affiliated_establishment_ids(user):
        raise PermissionDenied("Vous n'avez pas accès à la bibliothèque de cet établissement.")


class LibraryResourceListCreateView(generics.ListCreateAPIView):
    """Ressources de la bibliothèque numérique d'un établissement —
    consultables et alimentées par tout le personnel enseignant qui y est
    affilié (titulaire ou enseignant dédié d'au moins une classe/matière),
    ainsi que par le directeur."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LibraryResourceSerializer
    pagination_class = None

    def get_establishment(self):
        establishment = _get_establishment(self.kwargs["establishment_id"])
        _require_establishment_access(establishment, self.request.user)
        return establishment

    def get_queryset(self):
        establishment = self.get_establishment()
        user = self.request.user
        qs = LibraryResource.objects.filter(
            establishment=establishment, is_archived=False
        ).select_related("author")

        # Le grand public de l'établissement ne voit que les ressources
        # approuvées ; l'auteur d'une contribution voit en plus la sienne
        # quel que soit son statut (pour suivre si elle a été acceptée),
        # le directeur voit tout (file de modération).
        is_director_here = user.has_role(UserRole.DIRECTOR) and establishment.user_id == user.id
        if not is_director_here:
            qs = qs.filter(models.Q(moderation_status=ModerationStatus.APPROVED) | models.Q(author=user))

        params = self.request.query_params
        if params.get("subject"):
            qs = qs.filter(subject__iexact=params["subject"])
        if params.get("level"):
            qs = qs.filter(level=params["level"])
        if params.get("resource_type"):
            qs = qs.filter(resource_type=params["resource_type"])
        return qs

    def get_serializer_context(self):
        return {"request": self.request}

    def perform_create(self, serializer):
        establishment = self.get_establishment()
        user = self.request.user
        is_director = user.has_role(UserRole.DIRECTOR)

        if not is_director:
            if not user.has_role(UserRole.TEACHER):
                raise PermissionDenied("Seuls les enseignants et directeurs peuvent publier une ressource.")
            from apps.users.serializers import _current_certification_level

            if _current_certification_level(user) != "gold":
                raise PermissionDenied(
                    "La contribution à la bibliothèque est réservée aux enseignants certifiés Or."
                )

        file_url = serializer.validated_data.get("file_url")
        if file_url and LibraryResource.objects.filter(establishment=establishment, file_url=file_url).exists():
            raise ValidationError("Une ressource avec ce lien existe déjà dans cette bibliothèque.")

        # Le catalogue officiel du directeur reste publié immédiatement ;
        # une contribution d'enseignant passe par une modération (CDC
        # US-10-04 : soumission → revue admin → publication ou rejet).
        moderation_status = ModerationStatus.APPROVED if is_director else ModerationStatus.PENDING
        serializer.save(
            establishment=establishment, author=user, is_contributed=not is_director,
            moderation_status=moderation_status,
        )


class LibraryResourceDetailView(generics.RetrieveUpdateAPIView):
    """Détail d'une ressource — modifiable par son auteur ou le directeur
    de l'établissement (ex : archivage)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LibraryResourceSerializer

    def get_queryset(self):
        return LibraryResource.objects.select_related("author", "establishment")

    def get_object(self):
        resource = generics.get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        _require_establishment_access(resource.establishment, self.request.user)
        return resource

    def get_serializer_context(self):
        return {"request": self.request}

    def perform_update(self, serializer):
        resource = serializer.instance
        user = self.request.user
        is_director = user.has_role(UserRole.DIRECTOR) and resource.establishment.user_id == user.id
        if resource.author_id != user.id and not is_director:
            raise PermissionDenied("Réservé à l'auteur ou au directeur de l'établissement.")
        serializer.save()


class TrackResourceDownloadView(APIView):
    """Journalise un téléchargement et incrémente le compteur — appelé par
    le client juste avant d'ouvrir file_url."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            resource = LibraryResource.objects.select_related("establishment").get(pk=pk, is_archived=False)
        except LibraryResource.DoesNotExist:
            raise Http404
        _require_establishment_access(resource.establishment, request.user)

        ResourceDownload.objects.create(resource=resource, user=request.user)
        resource.download_count = F("download_count") + 1
        resource.save(update_fields=["download_count"])
        resource.refresh_from_db()
        return Response({"download_count": resource.download_count})


class ToggleFavoriteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_resource(self, pk, user):
        try:
            resource = LibraryResource.objects.select_related("establishment").get(pk=pk)
        except LibraryResource.DoesNotExist:
            raise Http404
        _require_establishment_access(resource.establishment, user)
        return resource

    def post(self, request, pk):
        resource = self._get_resource(pk, request.user)
        ResourceFavorite.objects.get_or_create(user=request.user, resource=resource)
        return Response(status=201)

    def delete(self, request, pk):
        resource = self._get_resource(pk, request.user)
        ResourceFavorite.objects.filter(user=request.user, resource=resource).delete()
        return Response(status=204)


class MyLibraryFavoritesView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LibraryResourceSerializer
    pagination_class = None

    def get_queryset(self):
        return LibraryResource.objects.filter(
            favorited_by__user=self.request.user, is_archived=False
        ).select_related("author")

    def get_serializer_context(self):
        return {"request": self.request}


class MyLibraryEstablishmentsView(APIView):
    """Établissements dont l'utilisateur connecté peut consulter la
    bibliothèque numérique — alimente le sélecteur côté frontend."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        ids = _affiliated_establishment_ids(request.user)
        establishments = DirectorProfile.objects.filter(id__in=ids).values("id", "school_name")
        return Response(list(establishments))
