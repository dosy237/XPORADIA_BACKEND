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
    path("teacher-profile/", views.TeacherProfileView.as_view(), name="teacher-profile"),
    path("director-profile/", views.DirectorProfileView.as_view(), name="director-profile"),
    path("parent-profile/", views.ParentProfileView.as_view(), name="parent-profile"),
    path("children/", views.ChildListCreateView.as_view(), name="children-list"),
    path("children/<int:pk>/", views.ChildDetailView.as_view(), name="children-detail"),
]
