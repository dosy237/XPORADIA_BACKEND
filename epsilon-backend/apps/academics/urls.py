from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("departments", views.DepartmentViewSet, basename="department")
router.register("tracks", views.TrackViewSet, basename="track")
router.register("classes", views.SchoolClassViewSet, basename="school-class")

urlpatterns = [
    path("my-classes/", views.MyHomeroomClassesView.as_view(), name="my-homeroom-classes"),
    path("my-subjects/", views.MyDedicatedSubjectsView.as_view(), name="my-dedicated-subjects"),
    path(
        "classes/<int:class_id>/subjects/",
        views.SubjectListCreateView.as_view(),
        name="subject-list",
    ),
    path("subjects/<int:pk>/", views.SubjectDetailView.as_view(), name="subject-detail"),
    path(
        "invitations/<str:token>/",
        views.TeacherInvitationPreviewView.as_view(),
        name="teacher-invitation-preview",
    ),
    path(
        "invitations/<str:token>/accept/",
        views.AcceptTeacherInvitationView.as_view(),
        name="accept-teacher-invitation",
    ),
    path("children-lookup/", views.ChildLookupView.as_view(), name="children-lookup"),
    path("classes/<int:class_id>/roster/", views.ClassRosterView.as_view(), name="class-roster"),
    path(
        "classes/<int:class_id>/batch-transition/",
        views.BatchRosterTransitionView.as_view(),
        name="batch-transition",
    ),
    path("year-end-readiness/", views.YearEndReadinessView.as_view(), name="year-end-readiness"),
    path("start-of-year-check/", views.StartOfYearCheckView.as_view(), name="start-of-year-check"),
    path(
        "roster/<int:enrollment_id>/correct-class/",
        views.CorrectEnrollmentClassView.as_view(),
        name="correct-enrollment-class",
    ),
    path("children/<int:child_id>/class/", views.ChildClassView.as_view(), name="child-class"),
    path("children/<int:child_id>/timetable/", views.ChildTimetableView.as_view(), name="child-timetable"),
    path("children/<int:child_id>/events/", views.ChildEventsView.as_view(), name="child-events"),
    path(
        "children/<int:child_id>/remove-from-establishment/",
        views.RemoveStudentFromEstablishmentView.as_view(),
        name="remove-from-establishment",
    ),
    path("classes/<int:class_id>/timetable/", views.TimetableView.as_view(), name="class-timetable"),
    path("timetable-slots/<int:pk>/", views.TimetableSlotDetailView.as_view(), name="timetable-slot-detail"),
    path("my-timetable/", views.MyTimetableView.as_view(), name="my-timetable"),
    path("my-agenda/", views.MyAgendaView.as_view(), name="my-agenda"),
    path(
        "personal-blocks/",
        views.PersonalScheduleBlockListCreateView.as_view(),
        name="personal-block-list",
    ),
    path(
        "personal-blocks/<int:pk>/occurrence/",
        views.PersonalScheduleBlockOccurrenceView.as_view(),
        name="personal-block-occurrence",
    ),
    path("classes/<int:class_id>/events/", views.ClassEventListCreateView.as_view(), name="class-event-list"),
    path("my-class/", views.MyClassView.as_view(), name="my-class"),
    path("my-delegations/", views.MyDelegationsView.as_view(), name="my-delegations"),
    path("task-delegations/", views.TaskDelegationsView.as_view(), name="task-delegations"),
    path(
        "subjects/<int:subject_id>/coefficient/",
        views.SubjectCoefficientView.as_view(),
        name="subject-coefficient",
    ),
    path(
        "my-timetable-delegation-classes/",
        views.MyTimetableDelegationClassesView.as_view(),
        name="my-timetable-delegation-classes",
    ),
    path(
        "departments/<int:department_id>/delegates/",
        views.DepartmentDelegatesView.as_view(),
        name="department-delegates",
    ),
    path("tracks/<int:track_id>/delegates/", views.TrackDelegatesView.as_view(), name="track-delegates"),
    path(
        "roster/<int:pk>/transition/",
        views.RosterEnrollmentTransitionView.as_view(),
        name="roster-transition",
    ),
    path("", include(router.urls)),
]
