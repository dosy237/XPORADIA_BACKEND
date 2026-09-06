from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import DirectorProfile, UserRole

from . import services
from .models import AdministrativeDocument
from .serializers import AdministrativeDocumentSerializer, IssueAdministrativeDocumentSerializer


def _get_establishment(user):
    if not user.has_role(UserRole.DIRECTOR):
        raise PermissionDenied("Réservé aux directeurs d'établissement.")
    return get_object_or_404(DirectorProfile, user=user)


def _get_child_in_establishment(child_id, establishment):
    """Un élève de cet établissement, inscription active OU passée — un
    certificat de radiation concerne justement un élève qui n'y est
    plus inscrit activement."""
    from apps.academics.models import Enrollment

    enrollment = Enrollment.objects.filter(
        child_id=child_id, school_class__track__department__establishment=establishment
    ).select_related("child").first()
    if not enrollment:
        raise Http404
    return enrollment.child


class AdministrativeDocumentListCreateView(generics.ListCreateAPIView):
    """Documents déjà émis pour un élève (?child_id=...) et émission
    d'un nouveau document — réservé au directeur de l'établissement où
    l'élève est ou a été inscrit."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def _child_id(self):
        child_id = self.request.query_params.get("child_id") or self.request.data.get("child_id")
        if not child_id:
            raise ValidationError({"child_id": "Paramètre obligatoire."})
        return child_id

    def get_serializer_class(self):
        return AdministrativeDocumentSerializer if self.request.method == "GET" else IssueAdministrativeDocumentSerializer

    def get_queryset(self):
        establishment = _get_establishment(self.request.user)
        child = _get_child_in_establishment(self._child_id(), establishment)
        return AdministrativeDocument.objects.filter(establishment=establishment, child=child).select_related(
            "issued_by"
        )

    def create(self, request, *args, **kwargs):
        establishment = _get_establishment(request.user)
        child = _get_child_in_establishment(self._child_id(), establishment)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = services.issue_administrative_document(
            establishment=establishment,
            child=child,
            document_type=serializer.validated_data["document_type"],
            school_year=serializer.validated_data["school_year"],
            issued_by=request.user,
        )
        return Response(
            AdministrativeDocumentSerializer(document, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@method_decorator(xframe_options_exempt, name="get")
class AdministrativeDocumentPdfView(APIView):
    """PDF régénéré à la demande à partir du document en base (numéro de
    référence et date d'émission fixés une fois pour toutes) — même
    principe que ReportCardPdfView : jamais servi depuis un fichier
    stocké, toujours reconstruit depuis la source de vérité en base."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        document = get_object_or_404(
            AdministrativeDocument.objects.select_related("establishment", "child", "issued_by"), pk=pk
        )
        establishment = _get_establishment(request.user)
        if document.establishment_id != establishment.id:
            raise PermissionDenied("Ce document n'appartient pas à votre établissement.")

        from .pdf import render_administrative_document_pdf

        pdf_bytes = render_administrative_document_pdf(document)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{document.reference_number}.pdf"'
        return response
