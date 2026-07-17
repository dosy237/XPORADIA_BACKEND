import datetime

import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, SchoolClass, Subject, Track
from apps.certification.models import (
    Certification,
    CertificationLevel,
    ExamAttempt,
    ExamQuestion,
    ModuleCategory,
    QuestionType,
    SessionEnrollment,
    SessionStatus,
    TrainingModule,
    TrainingSession,
)
from apps.notifications.models import Notification, NotificationType
from apps.payments.models import Payment, PaymentStatus
from apps.users.models import DirectorProfile, User, UserRole

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


def make_question(module, correct_answer, question_type=QuestionType.MCQ, **kwargs):
    defaults = {
        "text": "Question ?",
        "options": ["a", "b", "c"],
        "points": 1,
    }
    defaults.update(kwargs)
    return ExamQuestion.objects.create(
        module=module, question_type=question_type, correct_answer=correct_answer, **defaults
    )


def _create_director(email="director.cert@example.ci"):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="Adjoua", last_name="Kone",
        primary_role=UserRole.DIRECTOR,
    )
    profile = DirectorProfile.objects.create(user=user, school_name="École Test", address="Cocody")
    return user, profile


def _affiliate_teacher_to_establishment(profile, teacher):
    department = Department.objects.create(establishment=profile, name="Dept")
    track = Track.objects.create(department=department, name="Track")
    school_class = SchoolClass.objects.create(track=track, name="Classe", school_year="2025-2026")
    Subject.objects.create(school_class=school_class, name="Matière", teacher=teacher)


def test_online_exam_questions_excludes_open_questions_and_correct_answer(authed_client, teacher):
    module = make_module()
    mcq = make_question(module, "a", question_type=QuestionType.MCQ)
    make_question(module, "vrai réponse ouverte", question_type=QuestionType.OPEN)

    response = authed_client.get(f"/api/v1/certification/modules/{module.id}/online-exam/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["id"] == str(mcq.id)
    assert "correct_answer" not in response.data[0]


def test_online_exam_questions_forbidden_for_non_teacher(api_client):
    director, _ = _create_director()
    login = api_client.post(
        "/api/v1/auth/token/", {"email": director.email, "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    module = make_module()
    response = api_client.get(f"/api/v1/certification/modules/{module.id}/online-exam/")
    assert response.status_code == 403


def test_submit_online_exam_passes_and_issues_certification(authed_client, teacher):
    module = make_module(target_level=CertificationLevel.BRONZE)
    q1 = make_question(module, "a")
    q2 = make_question(module, "b")
    q3 = make_question(module, "vrai", question_type=QuestionType.TF)

    response = authed_client.post(
        f"/api/v1/certification/modules/{module.id}/online-exam/submit/",
        {"answers": {str(q1.id): "a", str(q2.id): "b", str(q3.id): "vrai"}},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["status"] == "passed"
    assert float(response.data["score_total"]) == 100.0
    assert response.data["leveled_up"] is True
    assert response.data["new_level"] == "bronze"

    assert Certification.objects.filter(teacher=teacher, module=module, is_valid=True).exists()
    attempt = ExamAttempt.objects.get(teacher=teacher, module=module)
    assert attempt.is_online is True
    assert attempt.session is None


def test_submit_online_exam_fails_below_threshold_no_certification(authed_client, teacher):
    module = make_module(target_level=CertificationLevel.BRONZE)
    q1 = make_question(module, "a")
    q2 = make_question(module, "b")
    q3 = make_question(module, "c")

    response = authed_client.post(
        f"/api/v1/certification/modules/{module.id}/online-exam/submit/",
        {"answers": {str(q1.id): "a", str(q2.id): "wrong", str(q3.id): "wrong"}},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["status"] == "failed"
    assert not Certification.objects.filter(teacher=teacher, module=module).exists()


def test_submit_online_exam_notifies_affiliated_establishment_on_level_up(authed_client, teacher):
    director, profile = _create_director()
    _affiliate_teacher_to_establishment(profile, teacher)

    module = make_module(target_level=CertificationLevel.BRONZE)
    q1 = make_question(module, "a")

    response = authed_client.post(
        f"/api/v1/certification/modules/{module.id}/online-exam/submit/",
        {"answers": {str(q1.id): "a"}},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["leveled_up"] is True

    from apps.notifications.models import Notification, NotificationType

    assert Notification.objects.filter(
        user=director, notif_type=NotificationType.EXAM_RESULT
    ).exists()


def test_submit_online_exam_requires_answers(authed_client):
    module = make_module()
    make_question(module, "a")
    response = authed_client.post(
        f"/api/v1/certification/modules/{module.id}/online-exam/submit/", {}, format="json"
    )
    assert response.status_code == 400


def test_submit_online_exam_no_gradable_questions_returns_400(authed_client):
    module = make_module()
    make_question(module, "texte libre", question_type=QuestionType.OPEN)
    response = authed_client.post(
        f"/api/v1/certification/modules/{module.id}/online-exam/submit/",
        {"answers": {"x": "y"}},
        format="json",
    )
    assert response.status_code == 400


def test_teacher_enrolls_in_session_and_pays(authed_client, teacher, trainer):
    module = make_module(price=20000)
    session = make_session(module, trainer)

    response = authed_client.post(
        f"/api/v1/certification/sessions/{session.id}/enroll/",
        {"operator": "orange", "phone_number": "0102030405"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["payment_status"] == "paid"
    assert response.data["payment"]["status"] == "completed"

    session.refresh_from_db()
    assert session.enrolled_count == 1

    payment = Payment.objects.get(user=teacher)
    assert payment.status == PaymentStatus.COMPLETED
    assert payment.amount == 20000

    assert Notification.objects.filter(user=teacher, notif_type=NotificationType.SESSION_CONFIRMED).exists()
    assert Notification.objects.filter(user=trainer, notif_type=NotificationType.SESSION_CONFIRMED).exists()


def test_cannot_enroll_twice_in_same_session(authed_client, trainer):
    module = make_module()
    session = make_session(module, trainer)

    authed_client.post(
        f"/api/v1/certification/sessions/{session.id}/enroll/",
        {"operator": "orange", "phone_number": "0102030405"},
        format="json",
    )
    response = authed_client.post(
        f"/api/v1/certification/sessions/{session.id}/enroll/",
        {"operator": "orange", "phone_number": "0102030405"},
        format="json",
    )
    assert response.status_code == 400


def test_cannot_enroll_in_full_session(authed_client, trainer):
    module = make_module()
    session = make_session(module, trainer, capacity=1, enrolled_count=1)

    response = authed_client.post(
        f"/api/v1/certification/sessions/{session.id}/enroll/",
        {"operator": "orange", "phone_number": "0102030405"},
        format="json",
    )
    assert response.status_code == 400


def test_enroll_requires_mobile_money_details(authed_client, trainer):
    module = make_module()
    session = make_session(module, trainer)

    response = authed_client.post(
        f"/api/v1/certification/sessions/{session.id}/enroll/", {}, format="json"
    )
    assert response.status_code == 400


def test_enroll_forbidden_for_non_teacher(api_client, trainer):
    module = make_module()
    session = make_session(module, trainer)
    director = User.objects.create_user(
        email="director.enroll@example.ci", password="testpass123",
        first_name="Adjoua", last_name="Kone", primary_role=UserRole.DIRECTOR,
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": director.email, "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.post(
        f"/api/v1/certification/sessions/{session.id}/enroll/",
        {"operator": "orange", "phone_number": "0102030405"},
        format="json",
    )
    assert response.status_code == 403


def test_my_enrollments_lists_own_only(authed_client, teacher, trainer):
    module = make_module()
    session = make_session(module, trainer)
    SessionEnrollment.objects.create(session=session, teacher=teacher, payment_status="paid")

    response = authed_client.get("/api/v1/certification/my-enrollments/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["session"]["id"] == str(session.id)
