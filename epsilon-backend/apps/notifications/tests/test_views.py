import pytest
from rest_framework.test import APIClient

from apps.notifications.models import Notification, NotificationChannel, NotificationType
from apps.users.models import User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def teacher(db):
    return User.objects.create_user(
        email="notif.teacher@example.ci", password="testpass123",
        first_name="N", last_name="T", primary_role=UserRole.TEACHER,
    )


@pytest.fixture
def authed_client(api_client, teacher):
    login = api_client.post(
        "/api/v1/auth/token/", {"email": teacher.email, "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return api_client


def test_notifications_require_authentication(api_client):
    response = api_client.get("/api/v1/notifications/")
    assert response.status_code == 401


def test_notifications_list_only_mine(authed_client, teacher):
    other = User.objects.create_user(
        email="other@example.ci", password="testpass123",
        first_name="O", last_name="T", primary_role=UserRole.TEACHER,
    )
    Notification.objects.create(
        user=teacher, notif_type=NotificationType.SYSTEM, channel=NotificationChannel.INAPP,
        title="Pour moi", body="...",
    )
    Notification.objects.create(
        user=other, notif_type=NotificationType.SYSTEM, channel=NotificationChannel.INAPP,
        title="Pas pour moi", body="...",
    )

    response = authed_client.get("/api/v1/notifications/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["title"] == "Pour moi"


def test_mark_notification_read(authed_client, teacher):
    notification = Notification.objects.create(
        user=teacher, notif_type=NotificationType.SYSTEM, channel=NotificationChannel.INAPP,
        title="Compte validé", body="...",
    )
    assert notification.is_read is False

    response = authed_client.post(f"/api/v1/notifications/{notification.id}/read/")
    assert response.status_code == 200
    assert response.data["is_read"] is True

    notification.refresh_from_db()
    assert notification.is_read is True
    assert notification.read_at is not None


def test_mark_notification_read_404_for_other_users_notification(authed_client):
    other = User.objects.create_user(
        email="other2@example.ci", password="testpass123",
        first_name="O", last_name="T", primary_role=UserRole.TEACHER,
    )
    notification = Notification.objects.create(
        user=other, notif_type=NotificationType.SYSTEM, channel=NotificationChannel.INAPP,
        title="Pas pour moi", body="...",
    )
    response = authed_client.post(f"/api/v1/notifications/{notification.id}/read/")
    assert response.status_code == 404
