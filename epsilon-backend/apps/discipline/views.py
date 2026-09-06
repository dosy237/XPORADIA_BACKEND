from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import DirectorProfile, UserRole

from . import services
from .models import DisciplinaryIncident
from .serializers import DisciplinaryIncidentSerializer, RecordIncidentSerializer


def _get_establishment(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")
    return get_object_or_404(DirectorProfile, user=user)


def _get_active_enrollment(child_id, establishment):
    from apps.academics.models import Enrollment, EnrollmentStatus

    enrollment = Enrollment.objects.filter(
        child_id=child_id,
        status=EnrollmentStatus.ACTIVE,
        school_class__track__department__establishment=establishment,
    ).select_related("child", "school_class").first()
    if not enrollment:
        raise Http404
    return enrollment


class ChildIncidentListCreateView(generics.ListCreateAPIView):
    """Incidents déjà consignés pour un élève (?child_id=...) et
    enregistrement d'un nouvel incident — réservé au directeur de
    l'établissement où l'élève est inscrit."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def _child_id(self):
        child_id = self.request.query_params.get("child_id") or self.request.data.get("child_id")
        if not child_id:
            raise ValidationError({"child_id": "Paramètre obligatoire."})
        return child_id

    def get_serializer_class(self):
        return DisciplinaryIncidentSerializer if self.request.method == "GET" else RecordIncidentSerializer

    def get_queryset(self):
        establishment = _get_establishment(self.request.user)
        enrollment = _get_active_enrollment(self._child_id(), establishment)
        return DisciplinaryIncident.objects.filter(
            establishment=establishment, child=enrollment.child
        ).select_related("school_class", "recorded_by")

    def create(self, request, *args, **kwargs):
        establishment = _get_establishment(request.user)
        enrollment = _get_active_enrollment(self._child_id(), establishment)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = DisciplinaryIncident.objects.create(
            establishment=establishment,
            child=enrollment.child,
            school_class=enrollment.school_class,
            recorded_by=request.user,
            **serializer.validated_data,
        )
        return Response(
            DisciplinaryIncidentSerializer(incident).data, status=status.HTTP_201_CREATED
        )


class NotifyParentAboutIncidentView(APIView):
    """Notifie le parent d'un incident déjà consigné — réutilise le
    système de notification existant, même principe que
    RemindLateFamilyView (apps.tuition)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, incident_id):
        from apps.notifications.models import NotificationType
        from apps.notifications.services import notify_user

        establishment = _get_establishment(request.user)
        incident = get_object_or_404(
            DisciplinaryIncident.objects.select_related("child__parent__user", "school_class"), pk=incident_id
        )
        if incident.establishment_id != establishment.id:
            raise PermissionDenied("Cet incident n'appartient pas à votre établissement.")

        child = incident.child
        if not (child.parent_id and child.parent.user_id):
            raise ValidationError("Aucun compte parent actif pour cet élève.")

        notify_user(
            child.parent.user,
            NotificationType.SYSTEM,
            title="Incident disciplinaire",
            body=f"Un incident ({incident.get_severity_display().lower()}) a été consigné pour "
                 f"{child.first_name} le {incident.occurred_on.strftime('%d/%m/%Y')} à "
                 f"{establishment.school_name}.",
        )
        incident.parent_notified_at = timezone.now()
        incident.save(update_fields=["parent_notified_at"])
        return Response(DisciplinaryIncidentSerializer(incident).data)


class EstablishmentIncidentsDashboardView(APIView):
    """Tableau de bord disciplinaire de l'établissement pour une année
    scolaire : totaux par gravité et incidents les plus récents."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        establishment = _get_establishment(request.user)
        school_year = request.query_params.get("school_year")
        if not school_year:
            raise ValidationError({"school_year": "Paramètre obligatoire."})

        totals = services.establishment_incident_totals(establishment, school_year)
        recent = DisciplinaryIncident.objects.filter(
            establishment=establishment, school_class__school_year=school_year
        ).select_related("child", "school_class", "recorded_by")[:20]
        return Response({
            "total": totals["total"],
            "by_severity": totals["by_severity"],
            "recent": DisciplinaryIncidentSerializer(recent, many=True).data,
        })
