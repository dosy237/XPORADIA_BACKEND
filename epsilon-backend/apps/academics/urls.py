from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("departments", views.DepartmentViewSet, basename="department")
router.register("tracks", views.TrackViewSet, basename="track")
router.register("classes", views.SchoolClassViewSet, basename="school-class")

urlpatterns = [
    path("my-classes/", views.MyHomeroomClassesView.as_view(), name="my-homeroom-classes"),
    path("my-subjects/", views.MyDedicatedSubjectsView.as_view(), name="my-dedicated-subjects"),
    path(
        "classes/<int:class_id>/subjects/",
        views.SubjectListCreateView.as_view(),
        name="subject-list",
    ),
    path("subjects/<int:pk>/", views.SubjectDetailView.as_view(), name="subject-detail"),
    path(
        "invitations/<str:token>/",
        views.TeacherInvitationPreviewView.as_view(),
        name="teacher-invitation-preview",
    ),
    path(
        "invitations/<str:token>/accept/",
        views.AcceptTeacherInvitationView.as_view(),
        name="accept-teacher-invitation",
    ),
    path("", include(router.urls)),
]
