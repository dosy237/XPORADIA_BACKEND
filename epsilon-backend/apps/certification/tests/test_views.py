import datetime

import pytest
from rest_framework.test import APIClient

from apps.certification.models import (
    Certification,
    CertificationLevel,
    ExamAttempt,
    ModuleCategory,
    SessionStatus,
    TrainingModule,
    TrainingSession,
)
from apps.users.models import User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def teacher(db):
    return User.objects.create_user(
        email="teacher.cert@example.ci", password="testpass123",
        first_name="Kouame", last_name="Yao", primary_role=UserRole.TEACHER,
    )


@pytest.fixture
def trainer(db):
    return User.objects.create_user(
        email="trainer@example.ci", password="testpass123",
        first_name="Konan", last_name="Assi", primary_role=UserRole.TRAINER,
    )


@pytest.fixture
def authed_client(api_client, teacher):
    login = api_client.post(
        "/api/v1/auth/token/", {"email": teacher.email, "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return api_client


def make_module(**kwargs):
    defaults = {
        "title": "Fondamentaux pédagogiques",
        "category": ModuleCategory.PEDAGOGY,
        "description": "Module de base.",
        "duration_hours": 8,
        "price": 15000,
        "target_level": CertificationLevel.BRONZE,
    }
    defaults.update(kwargs)
    return TrainingModule.objects.create(**defaults)


def make_session(module, trainer, **kwargs):
    defaults = {
        "city": "Abidjan",
        "location": "Cocody",
        "date": datetime.date.today() + datetime.timedelta(days=10),
        "start_time": "09:00",
        "end_time": "17:00",
        "capacity": 30,
        "status": SessionStatus.PLANNED,
    }
    defaults.update(kwargs)
    return TrainingSession.objects.create(module=module, trainer=trainer, **defaults)


def _results(response):
    return response.data["results"] if "results" in response.data else response.data


def test_training_modules_accessible_to_anonymous_visitors(api_client):
    make_module(title="Module public")
    response = api_client.get("/api/v1/certification/modules/")
    assert response.status_code == 200
    assert "Module public" in [m["title"] for m in _results(response)]


def test_training_sessions_accessible_to_anonymous_visitors(api_client, trainer):
    module = make_module()
    make_session(module, trainer, city="Abidjan")
    response = api_client.get("/api/v1/certification/sessions/")
    assert response.status_code == 200


def test_training_modules_list_returns_only_active(authed_client):
    make_module(title="Module actif")
    make_module(title="Module inactif", is_active=False)

    response = authed_client.get("/api/v1/certification/modules/")
    assert response.status_code == 200
    titles = [m["title"] for m in _results(response)]
    assert "Module actif" in titles
    assert "Module inactif" not in titles


def test_training_modules_filter_by_category_and_level(authed_client):
    make_module(title="Pédagogie Bronze", category=ModuleCategory.PEDAGOGY, target_level=CertificationLevel.BRONZE)
    make_module(title="Leadership Or", category=ModuleCategory.LEADERSHIP, target_level=CertificationLevel.GOLD)

    response = authed_client.get("/api/v1/certification/modules/?category=leadership")
    data = _results(response)
    assert len(data) == 1
    assert data[0]["title"] == "Leadership Or"

    response = authed_client.get("/api/v1/certification/modules/?target_level=bronze")
    data = _results(response)
    assert len(data) == 1
    assert data[0]["title"] == "Pédagogie Bronze"


def test_training_sessions_excludes_past_and_cancelled(authed_client, trainer):
    module = make_module()
    upcoming = make_session(module, trainer, city="Abidjan")
    make_session(
        module, trainer, city="Abidjan",
        date=datetime.date.today() - datetime.timedelta(days=5),
    )
    make_session(module, trainer, city="Abidjan", status=SessionStatus.CANCELLED)

    response = authed_client.get("/api/v1/certification/sessions/")
    assert response.status_code == 200
    data = _results(response)
    assert len(data) == 1
    assert data[0]["id"] == str(upcoming.id)


def test_training_sessions_filter_by_city(authed_client, trainer):
    module = make_module()
    make_session(module, trainer, city="Abidjan")
    make_session(module, trainer, city="Bouake")

    response = authed_client.get("/api/v1/certification/sessions/?city=Bouake")
    data = _results(response)
    assert len(data) == 1
    assert data[0]["city"] == "Bouake"


def test_my_status_requires_authentication(api_client):
    response = api_client.get("/api/v1/certification/my-status/")
    assert response.status_code == 401


def test_my_status_forbidden_for_non_teacher(api_client):
    director = User.objects.create_user(
        email="director.cert@example.ci", password="testpass123",
        first_name="Adjoua", last_name="Kone", primary_role=UserRole.DIRECTOR,
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": director.email, "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/certification/my-status/")
    assert response.status_code == 403


def test_my_status_no_certification_returns_null_level(authed_client):
    response = authed_client.get("/api/v1/certification/my-status/")
    assert response.status_code == 200
    assert response.data["current_level"] is None
    assert response.data["next_level"] == "bronze"
    assert response.data["certifications"] == []


def _issue_certification(teacher, trainer, level, is_valid=True):
    module = make_module(target_level=level)
    session = make_session(module, trainer)
    attempt = ExamAttempt.objects.create(teacher=teacher, session=session, score_total=85)
    return Certification.objects.create(
        teacher=teacher, module=module, attempt=attempt, level=level,
        score_total=85, qr_code=f"QR-{teacher.id}-{level}-{is_valid}",
        expires_at=datetime.date.today() + datetime.timedelta(days=365),
        is_valid=is_valid,
    )


def test_my_status_with_valid_bronze_certification(authed_client, teacher, trainer):
    _issue_certification(teacher, trainer, CertificationLevel.BRONZE)

    response = authed_client.get("/api/v1/certification/my-status/")
    assert response.status_code == 200
    assert response.data["current_level"] == "bronze"
    assert response.data["next_level"] == "silver"
    assert len(response.data["certifications"]) == 1


def test_my_status_ignores_revoked_certification(authed_client, teacher, trainer):
    _issue_certification(teacher, trainer, CertificationLevel.BRONZE, is_valid=False)

    response = authed_client.get("/api/v1/certification/my-status/")
    assert response.data["current_level"] is None
    assert response.data["certifications"] == []


def test_my_status_current_level_is_highest_achieved(authed_client, teacher, trainer):
    _issue_certification(teacher, trainer, CertificationLevel.BRONZE)
    _issue_certification(teacher, trainer, CertificationLevel.GOLD)

    response = authed_client.get("/api/v1/certification/my-status/")
    assert response.data["current_level"] == "gold"
    assert response.data["next_level"] is None
    assert set(response.data["levels_achieved"]) == {"bronze", "gold"}
