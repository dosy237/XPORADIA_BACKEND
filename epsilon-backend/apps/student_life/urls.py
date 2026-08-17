from django.urls import path

from . import views

urlpatterns = [
    path("notes/", views.PersonalNoteListCreateView.as_view(), name="personal-note-list"),
    path("notes/<int:pk>/", views.PersonalNoteDetailView.as_view(), name="personal-note-detail"),
    path("documents/", views.PersonalDocumentListCreateView.as_view(), name="personal-document-list"),
    path("documents/<int:pk>/", views.PersonalDocumentDetailView.as_view(), name="personal-document-detail"),
    path("life-goal/", views.LifeGoalView.as_view(), name="life-goal"),
    path("bucket-list/", views.BucketListItemListCreateView.as_view(), name="bucket-list-list"),
    path("bucket-list/<int:pk>/", views.BucketListItemDetailView.as_view(), name="bucket-list-detail"),
]
