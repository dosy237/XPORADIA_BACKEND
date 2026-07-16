from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("modules", views.TrainingModuleViewSet, basename="training-module")
router.register("sessions", views.TrainingSessionViewSet, basename="training-session")

urlpatterns = [
    path("my-status/", views.MyCertificationStatusView.as_view(), name="my-certification-status"),
    path(
        "modules/<uuid:module_id>/online-exam/",
        views.OnlineExamQuestionsView.as_view(),
        name="online-exam-questions",
    ),
    path(
        "modules/<uuid:module_id>/online-exam/submit/",
        views.SubmitOnlineExamView.as_view(),
        name="online-exam-submit",
    ),
    path("", include(router.urls)),
]
