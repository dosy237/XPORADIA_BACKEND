from django.urls import path

from . import views

urlpatterns = [
    path("dashboard-stats/", views.DashboardStatsView.as_view(), name="admin-dashboard-stats"),
    path("pending-accreditation/", views.PendingAccreditationView.as_view(), name="pending-accreditation"),
    path(
        "accreditation/<int:user_id>/validate/",
        views.ValidateAccreditationView.as_view(),
        name="validate-accreditation",
    ),
    path("pending-library/", views.PendingLibraryResourcesView.as_view(), name="admin-pending-library"),
    path(
        "library/<uuid:resource_id>/moderate/",
        views.ModerateLibraryResourceView.as_view(),
        name="moderate-library-resource",
    ),
    path("directory/<int:user_id>/toggle-partner/", views.TogglePartnerStatusView.as_view(), name="toggle-partner"),
    path(
        "directory/<int:user_id>/toggle-visibility/",
        views.ToggleProfileVisibilityView.as_view(),
        name="toggle-profile-visibility",
    ),
    path("users/", views.AdminUserListView.as_view(), name="admin-user-list"),
    path("users/<int:user_id>/", views.AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("users/<int:user_id>/suspend/", views.SuspendUserView.as_view(), name="suspend-user"),
    path("users/<int:user_id>/reactivate/", views.ReactivateUserView.as_view(), name="reactivate-user"),
    path(
        "certifications/<uuid:certification_id>/revoke/",
        views.RevokeCertificationView.as_view(),
        name="revoke-certification",
    ),
    path(
        "certifications/<uuid:certification_id>/reinstate/",
        views.ReinstateCertificationView.as_view(),
        name="reinstate-certification",
    ),
]
