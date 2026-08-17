from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("offers", views.InternshipOfferViewSet, basename="internship-offer")

urlpatterns = [
    path("my-applications/", views.MyInternshipApplicationsView.as_view(), name="my-internship-applications"),
    path("my-conventions/", views.MyConventionsView.as_view(), name="my-internship-conventions"),
    path(
        "offers/<uuid:offer_id>/applications/",
        views.OfferApplicationsView.as_view(),
        name="internship-offer-applications",
    ),
    path(
        "applications/<uuid:pk>/",
        views.InternshipApplicationDetailView.as_view(),
        name="internship-application-detail",
    ),
    path("conventions/<uuid:pk>/sign/", views.SignConventionView.as_view(), name="internship-convention-sign"),
    path(
        "conventions/<uuid:pk>/generate-pdf/",
        views.GenerateConventionPdfView.as_view(),
        name="internship-convention-generate-pdf",
    ),
    path(
        "conventions/<uuid:convention_id>/journal/",
        views.ConventionJournalView.as_view(),
        name="internship-convention-journal",
    ),
    path(
        "conventions/<uuid:convention_id>/evaluations/",
        views.ConventionEvaluationView.as_view(),
        name="internship-convention-evaluations",
    ),
    path(
        "conventions/<uuid:convention_id>/company-review/",
        views.SubmitCompanyReviewView.as_view(),
        name="submit-company-review",
    ),
    path("", include(router.urls)),
]
