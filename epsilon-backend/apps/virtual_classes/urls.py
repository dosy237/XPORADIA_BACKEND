from django.urls import path

from . import views

urlpatterns = [
    path(
        "subjects/<int:subject_id>/",
        views.SubjectVirtualClassView.as_view(),
        name="subject-virtual-class",
    ),
    path(
        "subjects/<int:subject_id>/exercises/",
        views.ExerciseListCreateView.as_view(),
        name="exercise-list",
    ),
    path("exercises/<uuid:pk>/", views.ExerciseDetailView.as_view(), name="exercise-detail"),
]
