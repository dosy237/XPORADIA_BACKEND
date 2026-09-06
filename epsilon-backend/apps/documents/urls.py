from django.urls import path

from .views import AdministrativeDocumentListCreateView, AdministrativeDocumentPdfView

urlpatterns = [
    path("administrative/", AdministrativeDocumentListCreateView.as_view(), name="administrative-documents"),
    path(
        "administrative/<int:pk>/pdf/",
        AdministrativeDocumentPdfView.as_view(),
        name="administrative-document-pdf",
    ),
]
