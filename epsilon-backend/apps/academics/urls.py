from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("departments", views.DepartmentViewSet, basename="department")
router.register("tracks", views.TrackViewSet, basename="track")
router.register("classes", views.SchoolClassViewSet, basename="school-class")

urlpatterns = [
    path("my-classes/", views.MyHomeroomClassesView.as_view(), name="my-homeroom-classes"),
    path("", include(router.urls)),
]
