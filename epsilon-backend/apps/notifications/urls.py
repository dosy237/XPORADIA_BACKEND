from django.urls import path

from . import views

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="notification-list"),
    path("<uuid:pk>/read/", views.MarkNotificationReadView.as_view(), name="notification-mark-read"),
    path("devices/register/", views.RegisterDeviceTokenView.as_view(), name="device-register"),
    path("devices/unregister/", views.UnregisterDeviceTokenView.as_view(), name="device-unregister"),
]
