from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.notifications.models import DeviceToken, Notification, NotificationChannel, NotificationType
from apps.notifications.services import notify_user
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


def test_register_device_requires_authentication(api_client):
    response = api_client.post(
        "/api/v1/notifications/devices/register/",
        {"token": "ExponentPushToken[abc]", "platform": "ios"},
        format="json",
    )
    assert response.status_code == 401


def test_register_device_creates_token(authed_client, teacher):
    response = authed_client.post(
        "/api/v1/notifications/devices/register/",
        {"token": "ExponentPushToken[abc]", "platform": "ios"},
        format="json",
    )
    assert response.status_code == 200
    token = DeviceToken.objects.get(token="ExponentPushToken[abc]")
    assert token.user == teacher
    assert token.platform == "ios"


def test_register_device_reassigns_token_to_new_user(authed_client, teacher):
    other = User.objects.create_user(
        email="deviceowner@example.ci", password="testpass123",
        first_name="D", last_name="O", primary_role=UserRole.TEACHER,
    )
    DeviceToken.objects.create(user=other, token="ExponentPushToken[shared]", platform="android")

    response = authed_client.post(
        "/api/v1/notifications/devices/register/",
        {"token": "ExponentPushToken[shared]", "platform": "android"},
        format="json",
    )
    assert response.status_code == 200
    token = DeviceToken.objects.get(token="ExponentPushToken[shared]")
    assert token.user == teacher


def test_unregister_device_removes_token(authed_client, teacher):
    DeviceToken.objects.create(user=teacher, token="ExponentPushToken[bye]", platform="ios")
    response = authed_client.post(
        "/api/v1/notifications/devices/unregister/", {"token": "ExponentPushToken[bye]"}, format="json"
    )
    assert response.status_code == 204
    assert not DeviceToken.objects.filter(token="ExponentPushToken[bye]").exists()


def test_unregister_device_cannot_remove_other_users_token(authed_client, teacher):
    other = User.objects.create_user(
        email="deviceowner2@example.ci", password="testpass123",
        first_name="D", last_name="O", primary_role=UserRole.TEACHER,
    )
    DeviceToken.objects.create(user=other, token="ExponentPushToken[notyours]", platform="ios")
    response = authed_client.post(
        "/api/v1/notifications/devices/unregister/", {"token": "ExponentPushToken[notyours]"}, format="json"
    )
    assert response.status_code == 204
    assert DeviceToken.objects.filter(token="ExponentPushToken[notyours]").exists()


def test_notify_user_creates_inapp_notification_and_sends_push(teacher):
    DeviceToken.objects.create(user=teacher, token="ExponentPushToken[push]", platform="ios")
    with patch("apps.notifications.services.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        notification = notify_user(teacher, NotificationType.SYSTEM, title="Titre", body="Corps")

    assert notification.title == "Titre"
    assert Notification.objects.filter(user=teacher, title="Titre").exists()
    mock_post.assert_called_once()
    sent_messages = mock_post.call_args.kwargs["json"]
    assert sent_messages[0]["to"] == "ExponentPushToken[push]"


def test_notify_user_skips_push_call_without_device_tokens(teacher):
    with patch("apps.notifications.services.requests.post") as mock_post:
        notify_user(teacher, NotificationType.SYSTEM, title="Titre", body="Corps")
    mock_post.assert_not_called()


def test_notify_user_survives_push_network_failure(teacher):
    import requests

    DeviceToken.objects.create(user=teacher, token="ExponentPushToken[fail]", platform="ios")
    with patch("apps.notifications.services.requests.post", side_effect=requests.RequestException("boom")):
        notification = notify_user(teacher, NotificationType.SYSTEM, title="Titre", body="Corps")
    assert notification is not None
