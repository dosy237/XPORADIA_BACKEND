from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BucketListItem, LifeGoal, PersonalDocument, PersonalNote
from .serializers import (
    BucketListItemSerializer,
    LifeGoalSerializer,
    PersonalDocumentSerializer,
    PersonalNoteSerializer,
)


def _require_own_child(request):
    """Tout ce module est strictement personnel — réservé au compte élève
    lui-même (pas même le parent, ni l'enseignant : ce sont des espaces
    d'autodiscipline privés, pas une donnée pédagogique partagée)."""
    child = getattr(request.user, "child_profile", None)
    if not child:
        raise PermissionDenied("Réservé aux comptes élève.")
    return child


class PersonalNoteListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PersonalNoteSerializer
    pagination_class = None

    def get_queryset(self):
        return PersonalNote.objects.filter(child=_require_own_child(self.request)).select_related("subject")

    def perform_create(self, serializer):
        serializer.save(child=_require_own_child(self.request))


class PersonalNoteDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PersonalNoteSerializer

    def get_queryset(self):
        return PersonalNote.objects.filter(child=_require_own_child(self.request))


class PersonalDocumentListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PersonalDocumentSerializer
    pagination_class = None

    def get_queryset(self):
        return PersonalDocument.objects.filter(child=_require_own_child(self.request))

    def perform_create(self, serializer):
        serializer.save(child=_require_own_child(self.request))


class PersonalDocumentDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PersonalDocumentSerializer

    def get_queryset(self):
        return PersonalDocument.objects.filter(child=_require_own_child(self.request))


class LifeGoalView(APIView):
    """Un seul objectif de vie par élève — GET renvoie un objet vide
    plutôt qu'un 404 s'il n'a encore rien renseigné (évite un aller-retour
    inutile côté app pour créer l'objet avant de pouvoir l'afficher)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        child = _require_own_child(request)
        goal, _ = LifeGoal.objects.get_or_create(child=child)
        return Response(LifeGoalSerializer(goal).data)

    def put(self, request):
        child = _require_own_child(request)
        goal, _ = LifeGoal.objects.get_or_create(child=child)
        serializer = LifeGoalSerializer(goal, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class BucketListItemListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BucketListItemSerializer
    pagination_class = None

    def get_queryset(self):
        return BucketListItem.objects.filter(child=_require_own_child(self.request))

    def perform_create(self, serializer):
        serializer.save(child=_require_own_child(self.request))


class BucketListItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BucketListItemSerializer

    def get_queryset(self):
        return BucketListItem.objects.filter(child=_require_own_child(self.request))

    def perform_update(self, serializer):
        was_done = serializer.instance.is_done
        instance = serializer.save()
        if instance.is_done and not was_done:
            instance.done_at = timezone.now()
            instance.save(update_fields=["done_at"])
        elif not instance.is_done and was_done:
            instance.done_at = None
            instance.save(update_fields=["done_at"])
