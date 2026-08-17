from django.urls import path

from . import views

urlpatterns = [
    path("register/teacher/", views.RegisterTeacherView.as_view(), name="register-teacher"),
    path("register/director/", views.RegisterDirectorView.as_view(), name="register-director"),
    path("register/parent/", views.RegisterParentView.as_view(), name="register-parent"),
    path("register/company/", views.RegisterCompanyView.as_view(), name="register-company"),
    path("register/student/", views.RegisterStudentView.as_view(), name="register-student"),
    path("token/", views.CustomTokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("token/refresh/", views.CustomTokenRefreshView.as_view(), name="token-refresh"),
    path("otp/verify/", views.VerifyOTPView.as_view(), name="otp-verify"),
    path("otp/resend/", views.ResendOTPView.as_view(), name="otp-resend"),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/avatar/", views.MyAvatarView.as_view(), name="me-avatar"),
    path("me/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("me/export/", views.MyDataExportView.as_view(), name="my-data-export"),
    path("me/request-deletion/", views.AccountDeletionRequestView.as_view(), name="request-deletion"),
    path("teacher-profile/", views.TeacherProfileView.as_view(), name="teacher-profile"),
    path(
        "me/submit-preregistration-code/",
        views.SubmitPreRegistrationCodeView.as_view(),
        name="submit-preregistration-code",
    ),
    path("students/invite/", views.StudentInviteCreateView.as_view(), name="student-invite-create"),
    path(
        "students/activate/<str:token>/",
        views.StudentActivationPreviewView.as_view(),
        name="student-activation-preview",
    ),
    path("students/activate/", views.StudentActivationView.as_view(), name="student-activation"),
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
    path(
        "establishments/",
        views.EstablishmentDirectoryViewSet.as_view({"get": "list"}),
        name="establishment-directory-list",
    ),
    path(
        "establishments/<int:user_id>/",
        views.EstablishmentDirectoryViewSet.as_view({"get": "retrieve"}),
        name="establishment-directory-detail",
    ),
    path(
        "companies/",
        views.CompanyDirectoryViewSet.as_view({"get": "list"}),
        name="company-directory-list",
    ),
    path(
        "companies/<int:user_id>/",
        views.CompanyDirectoryViewSet.as_view({"get": "retrieve"}),
        name="company-directory-detail",
    ),
    path(
        "teachers/<int:user_id>/comments/",
        views.TeacherCommentListCreateView.as_view(),
        name="teacher-comments",
    ),
    path("director-profile/", views.DirectorProfileView.as_view(), name="director-profile"),
    path("company-profile/", views.CompanyProfileView.as_view(), name="company-profile"),
    path("parent-profile/", views.ParentProfileView.as_view(), name="parent-profile"),
    path("children/", views.ChildListCreateView.as_view(), name="children-list"),
    path("children/<int:pk>/", views.ChildDetailView.as_view(), name="children-detail"),
    path("children/search-unclaimed/", views.SearchUnclaimedChildView.as_view(), name="search-unclaimed-child"),
    path("child-claim-requests/", views.CreateChildClaimRequestView.as_view(), name="create-child-claim"),
    path("my-child-claim-requests/", views.MyChildClaimRequestsView.as_view(), name="my-child-claims"),
    path(
        "child-claim-requests-for-me/",
        views.ChildClaimRequestsForMeView.as_view(),
        name="child-claims-for-me",
    ),
    path(
        "child-claim-requests/<int:pk>/review/",
        views.ReviewChildClaimRequestView.as_view(),
        name="review-child-claim",
    ),
    path("admin/create/", views.CreateAdminView.as_view(), name="create-admin"),
    path("admin/list/", views.AdminListView.as_view(), name="admin-list"),
]
