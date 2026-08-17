from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("listings", views.JobListingViewSet, basename="job-listing")

urlpatterns = [
    path("my-applications/", views.MyJobApplicationsView.as_view(), name="my-job-applications"),
    path("my-recruitments/", views.MyRecruitmentsView.as_view(), name="my-recruitments"),
    path("my-school-recruitments/", views.MySchoolRecruitmentsView.as_view(), name="my-school-recruitments"),
    path(
        "listings/<uuid:listing_id>/applications/",
        views.ListingApplicationsView.as_view(),
        name="listing-applications",
    ),
    path("applications/<uuid:pk>/", views.JobApplicationDetailView.as_view(), name="job-application-detail"),
    path(
        "job-seeking-requests/",
        views.JobSeekingRequestListCreateView.as_view(),
        name="job-seeking-requests",
    ),
    path(
        "my-job-seeking-request/",
        views.MyJobSeekingRequestView.as_view(),
        name="my-job-seeking-request",
    ),
    path(
        "recruitments/<uuid:recruitment_id>/worked-hours/",
        views.WorkedHoursListCreateView.as_view(),
        name="worked-hours-list",
    ),
    path("worked-hours/<int:pk>/review/", views.ReviewWorkedHoursView.as_view(), name="worked-hours-review"),
    path("my-wallet/", views.MyWalletView.as_view(), name="my-wallet"),
    path("my-invoices/", views.MyInvoicesView.as_view(), name="my-invoices"),
    path("invoices/<int:invoice_id>/pay/", views.PayInvoiceView.as_view(), name="pay-invoice"),
    path("my-salary-benchmark/", views.MySalaryBenchmarkView.as_view(), name="my-salary-benchmark"),
    path(
        "recruitments/<uuid:recruitment_id>/review/",
        views.CreateEmployerReviewView.as_view(),
        name="create-employer-review",
    ),
    path(
        "teachers/<int:teacher_id>/employment-history/",
        views.TeacherEmploymentHistoryView.as_view(),
        name="teacher-employment-history",
    ),
    path("", include(router.urls)),
]
