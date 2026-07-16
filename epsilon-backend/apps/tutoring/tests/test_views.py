import datetime

import pytest
from rest_framework.test import APIClient

from apps.notifications.models import Notification, NotificationType
from apps.payments.models import Payment, PaymentStatus
from apps.tutoring.models import TutoringReview, TutoringSession
from apps.users.models import ParentProfile, TeacherProfile, User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


def _create_teacher(email, hourly_rate="5000", available_for_tutoring=True):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="Yao", last_name="Kouassi",
        primary_role=UserRole.TEACHER,
    )
    TeacherProfile.objects.create(
        user=user, hourly_rate=hourly_rate, available_for_tutoring=available_for_tutoring
    )
    return user


def _create_parent(email):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="Aya", last_name="Bamba",
        primary_role=UserRole.PARENT,
    )
    ParentProfile.objects.create(user=user, location="Cocody")
    return user


def _login(api_client, email, password="testpass123"):
    login = api_client.post("/api/v1/auth/token/", {"email": email, "password": password}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")


def _booking_payload(teacher, **overrides):
    payload = {
        "teacher_id": teacher.id,
        "child_name": "Kouadio",
        "child_level": "6eme",
        "subject": "Mathématiques",
        "mode": "home",
        "date": str(datetime.date.today() + datetime.timedelta(days=3)),
        "start_time": "16:00",
        "duration_min": 60,
        "address": "Cocody, Abidjan",
        "operator": "orange",
        "phone_number": "0102030405",
    }
    payload.update(overrides)
    return payload


def test_parent_books_session_and_pays_into_escrow(api_client):
    teacher = _create_teacher("tutor.book@example.ci", hourly_rate="6000")
    parent = _create_parent("parent.book@example.ci")

    _login(api_client, parent.email)
    response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    assert response.status_code == 201
    assert response.data["status"] == "confirmed"
    assert response.data["gross_amount"] == 6000
    assert response.data["net_amount"] == 5100  # 15% commission

    session = TutoringSession.objects.get(parent=parent, teacher=teacher)
    payment = Payment.objects.get(user=parent)
    assert payment.status == PaymentStatus.ESCROW
    assert payment.amount == 6000
    assert Notification.objects.filter(user=teacher, notif_type=NotificationType.SESSION_CONFIRMED).exists()
    assert session.status == "confirmed"


def test_booking_forbidden_for_non_parent(api_client):
    teacher = _create_teacher("tutor.forbidden@example.ci")
    other_teacher = _create_teacher("tutor.other@example.ci")

    _login(api_client, other_teacher.email)
    response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    assert response.status_code == 403


def test_booking_rejected_for_unavailable_teacher(api_client):
    teacher = _create_teacher("tutor.unavailable2@example.ci", available_for_tutoring=False)
    parent = _create_parent("parent.unavailable@example.ci")

    _login(api_client, parent.email)
    response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    assert response.status_code == 400


def test_booking_requires_mobile_money_details(api_client):
    teacher = _create_teacher("tutor.nomoney@example.ci")
    parent = _create_parent("parent.nomoney@example.ci")

    _login(api_client, parent.email)
    response = api_client.post(
        "/api/v1/tutoring/my-sessions/",
        _booking_payload(teacher, operator="", phone_number=""),
        format="json",
    )
    assert response.status_code == 400


def test_my_sessions_lists_for_both_roles(api_client):
    teacher = _create_teacher("tutor.list@example.ci")
    parent = _create_parent("parent.list@example.ci")

    _login(api_client, parent.email)
    api_client.post("/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json")

    response = api_client.get("/api/v1/tutoring/my-sessions/")
    assert response.status_code == 200
    assert len(response.data) == 1

    _login(api_client, teacher.email)
    response = api_client.get("/api/v1/tutoring/my-sessions/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["payment"]["status"] == "escrow"


def test_teacher_completes_session_releases_escrow_and_notifies(api_client):
    teacher = _create_teacher("tutor.complete@example.ci", hourly_rate="4000")
    parent = _create_parent("parent.complete@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    _login(api_client, teacher.email)
    response = api_client.patch(
        f"/api/v1/tutoring/sessions/{session_id}/", {"status": "completed"}, format="json"
    )
    assert response.status_code == 200

    session = TutoringSession.objects.get(id=session_id)
    assert session.status == "completed"
    assert session.escrow_released is True

    payment = Payment.objects.get(user=parent)
    assert payment.status == PaymentStatus.COMPLETED

    assert Notification.objects.filter(user=parent, notif_type=NotificationType.SESSION_CONFIRMED).exists()
    assert Notification.objects.filter(user=teacher, notif_type=NotificationType.PAYMENT_RECEIVED).exists()


def test_only_teacher_can_mark_completed(api_client):
    teacher = _create_teacher("tutor.onlyteacher@example.ci")
    parent = _create_parent("parent.onlyteacher@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    response = api_client.patch(
        f"/api/v1/tutoring/sessions/{session_id}/", {"status": "completed"}, format="json"
    )
    assert response.status_code == 403


def test_cancelling_session_refunds_payment_and_notifies_other_party(api_client):
    teacher = _create_teacher("tutor.cancel@example.ci")
    parent = _create_parent("parent.cancel@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    response = api_client.patch(
        f"/api/v1/tutoring/sessions/{session_id}/",
        {"status": "cancelled", "cancel_reason": "Empêchement"},
        format="json",
    )
    assert response.status_code == 200

    payment = Payment.objects.get(user=parent)
    assert payment.status == PaymentStatus.REFUNDED
    assert Notification.objects.filter(user=teacher, notif_type=NotificationType.SESSION_CANCELLED).exists()


def test_detail_forbidden_for_unrelated_user(api_client):
    teacher = _create_teacher("tutor.detailforbid@example.ci")
    parent = _create_parent("parent.detailforbid@example.ci")
    intruder = _create_parent("parent.intruder@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    _login(api_client, intruder.email)
    response = api_client.get(f"/api/v1/tutoring/sessions/{session_id}/")
    assert response.status_code == 403


def test_parent_reviews_completed_session(api_client):
    teacher = _create_teacher("tutor.review@example.ci")
    parent = _create_parent("parent.review@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    _login(api_client, teacher.email)
    api_client.patch(f"/api/v1/tutoring/sessions/{session_id}/", {"status": "completed"}, format="json")

    _login(api_client, parent.email)
    response = api_client.post(
        f"/api/v1/tutoring/sessions/{session_id}/reviews/",
        {"rating": 5, "comment": "Excellent enseignant."},
        format="json",
    )
    assert response.status_code == 201
    assert TutoringReview.objects.filter(session_id=session_id, author=parent, rating=5).exists()


def test_cannot_review_uncompleted_session(api_client):
    teacher = _create_teacher("tutor.reviewearly@example.ci")
    parent = _create_parent("parent.reviewearly@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    response = api_client.post(
        f"/api/v1/tutoring/sessions/{session_id}/reviews/", {"rating": 4}, format="json"
    )
    assert response.status_code == 403


def test_cannot_review_twice(api_client):
    teacher = _create_teacher("tutor.reviewtwice@example.ci")
    parent = _create_parent("parent.reviewtwice@example.ci")

    _login(api_client, parent.email)
    create_response = api_client.post(
        "/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json"
    )
    session_id = create_response.data["id"]

    _login(api_client, teacher.email)
    api_client.patch(f"/api/v1/tutoring/sessions/{session_id}/", {"status": "completed"}, format="json")

    _login(api_client, parent.email)
    api_client.post(f"/api/v1/tutoring/sessions/{session_id}/reviews/", {"rating": 5}, format="json")
    response = api_client.post(
        f"/api/v1/tutoring/sessions/{session_id}/reviews/", {"rating": 3}, format="json"
    )
    assert response.status_code == 400


def test_my_payments_lists_own_history(api_client):
    teacher = _create_teacher("tutor.payments@example.ci")
    parent = _create_parent("parent.payments@example.ci")

    _login(api_client, parent.email)
    api_client.post("/api/v1/tutoring/my-sessions/", _booking_payload(teacher), format="json")

    response = api_client.get("/api/v1/payments/my-payments/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["status"] == "escrow"

    _login(api_client, teacher.email)
    response = api_client.get("/api/v1/payments/my-payments/")
    assert response.status_code == 200
    assert len(response.data) == 0
