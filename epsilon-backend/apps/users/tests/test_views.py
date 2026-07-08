import pytest
from rest_framework.test import APIClient

from apps.users.models import OTPCode, User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


def test_register_teacher_creates_user_and_profile(api_client):
    response = api_client.post(
        "/api/v1/auth/register/teacher/",
        {
            "email": "kouame@example.ci",
            "password": "testpass123",
            "first_name": "Kouame",
            "last_name": "Yao",
            "phone": "+225070000001",
            "subjects": ["Maths", "Physique"],
            "experience_years": 4,
        },
        format="json",
    )
    assert response.status_code == 201
    user = User.objects.get(email="kouame@example.ci")
    assert user.primary_role == UserRole.TEACHER
    assert user.teacher_profile.subjects == ["Maths", "Physique"]
    assert not user.is_verified


def test_register_teacher_duplicate_email_rejected(api_client):
    payload = {
        "email": "dup@example.ci", "password": "testpass123",
        "first_name": "A", "last_name": "B",
    }
    first = api_client.post("/api/v1/auth/register/teacher/", payload, format="json")
    assert first.status_code == 201
    second = api_client.post("/api/v1/auth/register/teacher/", payload, format="json")
    assert second.status_code == 400


def test_register_director_creates_school_profile(api_client):
    response = api_client.post(
        "/api/v1/auth/register/director/",
        {
            "email": "adjoua@example.ci", "password": "testpass123",
            "first_name": "Adjoua", "last_name": "Kone",
            "school_name": "Lycee Prive Cocody", "address": "Cocody, Abidjan",
        },
        format="json",
    )
    assert response.status_code == 201
    user = User.objects.get(email="adjoua@example.ci")
    assert user.director_profile.school_name == "Lycee Prive Cocody"


def test_register_company_creates_company_profile(api_client):
    response = api_client.post(
        "/api/v1/auth/register/company/",
        {
            "email": "acme@example.ci", "password": "testpass123",
            "first_name": "Awa", "last_name": "Traore",
            "company_name": "ACME Abidjan", "sector": "BTP",
            "address": "Plateau, Abidjan",
        },
        format="json",
    )
    assert response.status_code == 201
    user = User.objects.get(email="acme@example.ci")
    assert user.primary_role == UserRole.COMPANY
    assert user.company_profile.company_name == "ACME Abidjan"


def test_register_parent_with_children(api_client):
    response = api_client.post(
        "/api/v1/auth/register/parent/",
        {
            "email": "serge@example.ci", "password": "testpass123",
            "first_name": "Serge", "last_name": "Kouassi",
            "children": [
                {"first_name": "Awa", "class_level": "3eme", "target_subjects": ["Maths"]}
            ],
        },
        format="json",
    )
    assert response.status_code == 201
    user = User.objects.get(email="serge@example.ci")
    assert user.parent_profile.children.count() == 1


def test_register_parent_rejects_more_than_five_children(api_client):
    children = [{"first_name": f"Enfant{i}", "class_level": "6eme"} for i in range(6)]
    response = api_client.post(
        "/api/v1/auth/register/parent/",
        {
            "email": "manykids@example.ci", "password": "testpass123",
            "first_name": "Serge", "last_name": "Kouassi", "children": children,
        },
        format="json",
    )
    assert response.status_code == 400


def test_login_returns_tokens_and_user(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "login@example.ci", "password": "testpass123", "first_name": "L", "last_name": "T"},
        format="json",
    )
    response = api_client.post(
        "/api/v1/auth/token/",
        {"email": "login@example.ci", "password": "testpass123"},
        format="json",
    )
    assert response.status_code == 200
    assert "access" in response.data and "refresh" in response.data
    assert response.data["user"]["email"] == "login@example.ci"


def test_login_wrong_password_rejected(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "wrongpass@example.ci", "password": "testpass123", "first_name": "L", "last_name": "T"},
        format="json",
    )
    response = api_client.post(
        "/api/v1/auth/token/",
        {"email": "wrongpass@example.ci", "password": "nope"},
        format="json",
    )
    assert response.status_code == 401


def test_me_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/me/")
    assert response.status_code == 401


def test_me_returns_current_user(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "me@example.ci", "password": "testpass123", "first_name": "M", "last_name": "E"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "me@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/auth/me/")
    assert response.status_code == 200
    assert response.data["email"] == "me@example.ci"


def test_otp_verify_activates_account(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "otpflow@example.ci", "password": "testpass123", "first_name": "O", "last_name": "F"},
        format="json",
    )
    user = User.objects.get(email="otpflow@example.ci")
    otp = OTPCode.objects.filter(user=user).latest("created_at")
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "otpflow@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    bad = api_client.post("/api/v1/auth/otp/verify/", {"code": "000000"}, format="json")
    assert bad.status_code == 400

    good = api_client.post("/api/v1/auth/otp/verify/", {"code": otp.code}, format="json")
    assert good.status_code == 200
    user.refresh_from_db()
    assert user.is_verified


def test_teacher_profile_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/teacher-profile/")
    assert response.status_code == 401


def test_teacher_profile_get_and_update(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {
            "email": "profile@example.ci", "password": "testpass123",
            "first_name": "P", "last_name": "R", "subjects": ["Maths"], "experience_years": 2,
        },
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "profile@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    get_response = api_client.get("/api/v1/auth/teacher-profile/")
    assert get_response.status_code == 200
    assert get_response.data["subjects"] == ["Maths"]

    patch_response = api_client.patch(
        "/api/v1/auth/teacher-profile/",
        {"bio": "Prof de maths passionné.", "hourly_rate": "5000", "available_for_tutoring": True},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["bio"] == "Prof de maths passionné."
    assert patch_response.data["available_for_tutoring"] is True


def test_teacher_profile_forbidden_for_other_roles(api_client):
    api_client.post(
        "/api/v1/auth/register/parent/",
        {"email": "notteacher@example.ci", "password": "testpass123", "first_name": "N", "last_name": "T"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "notteacher@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/auth/teacher-profile/")
    assert response.status_code == 403
