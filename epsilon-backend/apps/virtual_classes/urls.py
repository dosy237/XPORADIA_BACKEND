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
    path(
        "exercises/<uuid:exercise_id>/submissions/stats/",
        views.ExerciseSubmissionStatsView.as_view(),
        name="exercise-submission-stats",
    ),
    path("submissions/<int:pk>/", views.SubmissionDetailView.as_view(), name="submission-detail"),
    path("my-submissions/", views.MySubmissionsView.as_view(), name="my-submissions"),
    path("my-subjects/", views.MySubjectsView.as_view(), name="my-subjects"),
    path(
        "classes/<int:class_id>/exercises-overview/",
        views.HomeroomExercisesOverviewView.as_view(),
        name="homeroom-exercises-overview",
    ),
    path("my-grading-queue/", views.MyGradingQueueView.as_view(), name="my-grading-queue"),
]
