from django.urls import path

from . import views

urlpatterns = [
    path("channels/", views.ChannelListView.as_view(), name="channel-list"),
    path("channels/<int:channel_id>/messages/", views.ChannelMessagesView.as_view(), name="channel-messages"),
    path("messages/<int:pk>/", views.MessageDetailView.as_view(), name="message-detail"),
    path("channels/<int:channel_id>/read/", views.MarkChannelReadView.as_view(), name="channel-mark-read"),
    path(
        "subjects/<int:subject_id>/create-channel/",
        views.CreateSubjectChannelView.as_view(),
        name="subject-channel-create",
    ),
    path("contact-child-teacher/", views.ContactChildTeacherView.as_view(), name="contact-child-teacher"),
]
