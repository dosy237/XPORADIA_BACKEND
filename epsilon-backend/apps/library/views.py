from django.db.models import F
from django.http import Http404
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import SchoolClass, Subject
from apps.users.models import DirectorProfile, UserRole

from .models import LibraryResource, ResourceDownload, ResourceFavorite
from .serializers import LibraryResourceSerializer


def _affiliated_establishment_ids(user):
    """Établissements où l'utilisateur est directeur, titulaire d'une
    classe, ou enseignant dédié d'une matière — donc légitime à consulter
    (et contribuer à) la bibliothèque numérique de cet établissement."""

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
        qs = LibraryResource.objects.filter(
            establishment=establishment, is_archived=False
        ).select_related("author")
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
        serializer.save(establishment=establishment, author=self.request.user, is_contributed=True)


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
