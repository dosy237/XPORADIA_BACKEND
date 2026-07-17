from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("listings", views.JobListingViewSet, basename="job-listing")

urlpatterns = [
    path("my-applications/", views.MyJobApplicationsView.as_view(), name="my-job-applications"),
    path("my-recruitments/", views.MyRecruitmentsView.as_view(), name="my-recruitments"),
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
    path("", include(router.urls)),
]
