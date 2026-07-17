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
    path("children/<int:child_id>/subjects/", views.ChildSubjectsView.as_view(), name="child-subjects"),
    path(
        "exercises/<uuid:exercise_id>/submissions/",
        views.ExerciseSubmissionsView.as_view(),
        name="exercise-submissions",
    ),
    path("submissions/<int:pk>/", views.SubmissionDetailView.as_view(), name="submission-detail"),
    path("my-submissions/", views.MySubmissionsView.as_view(), name="my-submissions"),
]
