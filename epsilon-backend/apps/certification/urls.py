from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("modules", views.TrainingModuleViewSet, basename="training-module")
router.register("sessions", views.TrainingSessionViewSet, basename="training-session")
router.register("admin/modules", views.AdminTrainingModuleViewSet, basename="admin-training-module")

urlpatterns = [
    path("verify/<str:qr_code>/", views.PublicCertificationVerificationView.as_view(), name="verify-certification"),
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
    path(
        "modules/<uuid:module_id>/retake/eligibility/",
        views.RetakeEligibilityView.as_view(),
        name="retake-eligibility",
    ),
    path("modules/<uuid:module_id>/retake/", views.RetakeExamView.as_view(), name="retake-exam"),
    path(
        "sessions/<uuid:session_id>/enroll/",
        views.EnrollInSessionView.as_view(),
        name="session-enroll",
    ),
    path("my-enrollments/", views.MySessionEnrollmentsView.as_view(), name="my-session-enrollments"),
    path("", include(router.urls)),
]
