from django.urls import path

from . import views

urlpatterns = [
    path("my-sessions/", views.MyTutoringSessionsView.as_view(), name="my-tutoring-sessions"),
    path("sessions/<uuid:pk>/", views.TutoringSessionDetailView.as_view(), name="tutoring-session-detail"),
    path("sessions/<uuid:session_id>/reviews/", views.SessionReviewsView.as_view(), name="session-reviews"),
]
