from django.urls import path

from .views import (
    ChildIncidentListCreateView,
    EstablishmentIncidentsDashboardView,
    NotifyParentAboutIncidentView,
)

urlpatterns = [
    path("incidents/", ChildIncidentListCreateView.as_view(), name="incidents"),
    path("incidents/<int:incident_id>/notify/", NotifyParentAboutIncidentView.as_view(), name="incident-notify"),
    path("dashboard/", EstablishmentIncidentsDashboardView.as_view(), name="incidents-dashboard"),
]
