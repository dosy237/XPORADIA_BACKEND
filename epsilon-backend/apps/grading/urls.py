from django.urls import path

from . import views

urlpatterns = [
    path("terms/", views.TermListCreateView.as_view(), name="term-list"),
    path("terms/<int:pk>/", views.TermDetailView.as_view(), name="term-detail"),
    path("classes/<int:class_id>/active-term/", views.MyActiveTermView.as_view(), name="active-term"),
    path("classes/<int:class_id>/terms/", views.ClassTermsView.as_view(), name="class-terms"),
    path(
        "subjects/<int:subject_id>/evaluations/",
        views.EvaluationListCreateView.as_view(),
        name="evaluation-list",
    ),
    path("evaluations/<int:pk>/", views.EvaluationDetailView.as_view(), name="evaluation-detail"),
    path(
        "evaluations/<int:evaluation_id>/grades/",
        views.EvaluationGradesView.as_view(),
        name="evaluation-grades",
    ),
    path("subjects/<int:subject_id>/terms/", views.SubjectTermsView.as_view(), name="subject-terms"),
    path(
        "subjects/<int:subject_id>/terms/<int:term_id>/grade-grid/",
        views.SubjectGradeGridView.as_view(),
        name="subject-grade-grid",
    ),
    path(
        "subjects/<int:subject_id>/terms/<int:term_id>/students/<int:child_id>/appreciation/",
        views.SubjectStudentAppreciationView.as_view(),
        name="subject-student-appreciation",
    ),
    path(
        "classes/<int:class_id>/terms/<int:term_id>/report-preview/",
        views.ClassReportPreviewView.as_view(),
        name="class-report-preview",
    ),
    path(
        "classes/<int:class_id>/terms/<int:term_id>/generate-report-cards/",
        views.GenerateReportCardsView.as_view(),
        name="generate-report-cards",
    ),
    path("my-report-cards/", views.MyReportCardsView.as_view(), name="my-report-cards"),
    path("my-grades/", views.MyGradesView.as_view(), name="my-grades"),
    path(
        "children/<int:child_id>/report-cards/",
        views.ChildReportCardsView.as_view(),
        name="child-report-cards",
    ),
    path("join-requests/", views.JoinRequestCreateView.as_view(), name="join-request-create"),
    path("my-join-request/", views.MyJoinRequestView.as_view(), name="my-join-request"),
    path(
        "director-join-requests/",
        views.DirectorJoinRequestsView.as_view(),
        name="director-join-requests",
    ),
    path(
        "join-requests/<int:pk>/review/",
        views.ReviewJoinRequestView.as_view(),
        name="review-join-request",
    ),
    path(
        "approved-unplaced-children/",
        views.ApprovedUnplacedChildrenView.as_view(),
        name="approved-unplaced-children",
    ),
    path("admission-report/parse/", views.ParseAdmissionReportView.as_view(), name="admission-report-parse"),
    path(
        "admission-report/confirm/",
        views.ConfirmAdmissionReportView.as_view(),
        name="admission-report-confirm",
    ),
]
