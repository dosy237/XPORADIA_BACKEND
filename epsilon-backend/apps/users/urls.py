from django.urls import path

from . import views

urlpatterns = [
    path("register/teacher/", views.RegisterTeacherView.as_view(), name="register-teacher"),
    path("register/director/", views.RegisterDirectorView.as_view(), name="register-director"),
    path("register/parent/", views.RegisterParentView.as_view(), name="register-parent"),
    path("register/company/", views.RegisterCompanyView.as_view(), name="register-company"),
    path("token/", views.CustomTokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("token/refresh/", views.CustomTokenRefreshView.as_view(), name="token-refresh"),
    path("otp/verify/", views.VerifyOTPView.as_view(), name="otp-verify"),
    path("otp/resend/", views.ResendOTPView.as_view(), name="otp-resend"),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("me/export/", views.MyDataExportView.as_view(), name="my-data-export"),
    path("me/request-deletion/", views.AccountDeletionRequestView.as_view(), name="request-deletion"),
    path("teacher-profile/", views.TeacherProfileView.as_view(), name="teacher-profile"),
    path(
        "me/submit-preregistration-code/",
        views.SubmitPreRegistrationCodeView.as_view(),
        name="submit-preregistration-code",
    ),
    path(
        "teachers/",
        views.TeacherDirectoryViewSet.as_view({"get": "list"}),
        name="teacher-directory-list",
    ),
    path(
        "teachers/<int:user_id>/",
        views.TeacherDirectoryViewSet.as_view({"get": "retrieve"}),
        name="teacher-directory-detail",
    ),
    path("director-profile/", views.DirectorProfileView.as_view(), name="director-profile"),
    path("company-profile/", views.CompanyProfileView.as_view(), name="company-profile"),
    path("parent-profile/", views.ParentProfileView.as_view(), name="parent-profile"),
    path("children/", views.ChildListCreateView.as_view(), name="children-list"),
    path("children/<int:pk>/", views.ChildDetailView.as_view(), name="children-detail"),
]
