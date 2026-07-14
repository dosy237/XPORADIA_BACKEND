import datetime

import pytest
from rest_framework.test import APIClient

from apps.certification.models import Certification, CertificationLevel, ExamAttempt, TrainingModule, TrainingSession
from apps.employment.models import JobApplication, JobListing, JobSeekingRequest, Recruitment
from apps.notifications.models import Notification
from apps.users.models import DirectorProfile, TeacherProfile, User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


def _create_director(email="director@example.ci", school_name="Groupe Scolaire Test"):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="D", last_name="R",
        primary_role=UserRole.DIRECTOR,
    )
    DirectorProfile.objects.create(user=user, school_name=school_name, address="Cocody")
    return user


def _create_teacher(email="teacher@example.ci"):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="T", last_name="E",
        primary_role=UserRole.TEACHER,
    )
    TeacherProfile.objects.create(user=user)
    return user


def _login(api_client, email, password="testpass123"):
    login = api_client.post("/api/v1/auth/token/", {"email": email, "password": password}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")


def _create_listing(director, status="draft", **kwargs):
    defaults = {
        "school": director, "title": "Prof de Maths", "subject": "Mathématiques",
        "contract_type": "cdi", "description": "Poste à pourvoir.", "city": "Abidjan",
        "status": status,
    }
    defaults.update(kwargs)
    return JobListing.objects.create(**defaults)


def _make_gold_teacher(email="gold.teacher@example.ci"):
    teacher = _create_teacher(email=email)
    trainer = User.objects.create_user(
        email=f"trainer.{email}", password="testpass123", first_name="Tr", last_name="A",
        primary_role=UserRole.TRAINER,
    )
    module = TrainingModule.objects.create(
        title="Leadership", category="leadership", description="...",
        duration_hours=8, price=10000, target_level=CertificationLevel.GOLD,
    )
    session = TrainingSession.objects.create(
        module=module, trainer=trainer, city="Abidjan", location="Centre",
        date=datetime.date.today(), start_time="09:00", end_time="17:00",
    )
    attempt = ExamAttempt.objects.create(teacher=teacher, session=session, score_total=90)
    Certification.objects.create(
        teacher=teacher, module=module, attempt=attempt, level=CertificationLevel.GOLD,
        score_total=90, qr_code=f"QR-{email}",
        expires_at=datetime.date.today() + datetime.timedelta(days=365),
    )
    return teacher


def test_listing_list_is_public_and_excludes_non_active(api_client):
    director = _create_director()
    _create_listing(director, status="active", title="Actif")
    _create_listing(director, status="draft", title="Brouillon")

    response = api_client.get("/api/v1/employment/listings/")
    assert response.status_code == 200
    titles = [r["title"] for r in response.data]
    assert "Actif" in titles
    assert "Brouillon" not in titles


def test_director_list_shows_own_drafts_but_not_other_directors_listings(api_client):
    director = _create_director(email="ownlisting@example.ci")
    other = _create_director(email="otherlisting@example.ci")
    _create_listing(director, status="draft", title="Mon brouillon")
    _create_listing(director, status="active", title="Ma active")
    _create_listing(other, status="active", title="Offre concurrente")
    _login(api_client, director.email)

    response = api_client.get("/api/v1/employment/listings/")
    assert response.status_code == 200
    titles = [r["title"] for r in response.data]
    assert "Mon brouillon" in titles
    assert "Ma active" in titles
    assert "Offre concurrente" not in titles


def test_listing_create_forbidden_for_teacher(api_client):
    teacher = _create_teacher()
    _login(api_client, teacher.email)

    response = api_client.post(
        "/api/v1/employment/listings/",
        {"title": "X", "subject": "Maths", "contract_type": "cdi", "description": "...", "city": "Abidjan"},
        format="json",
    )
    assert response.status_code == 403


def test_director_creates_listing_as_draft(api_client):
    director = _create_director()
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/employment/listings/",
        {
            "title": "Prof de Physique", "subject": "Physique", "contract_type": "cdd",
            "description": "Poste temporaire.", "city": "Bouaké",
        },
        format="json",
    )
    assert response.status_code == 201
    listing = JobListing.objects.get(title="Prof de Physique")
    assert listing.status == "draft"
    assert listing.school == director


def test_director_publishes_and_closes_own_listing(api_client):
    director = _create_director()
    listing = _create_listing(director, status="draft")
    _login(api_client, director.email)

    publish_response = api_client.post(f"/api/v1/employment/listings/{listing.id}/publish/")
    assert publish_response.status_code == 200
    listing.refresh_from_db()
    assert listing.status == "active"
    assert listing.published_at is not None

    close_response = api_client.post(f"/api/v1/employment/listings/{listing.id}/close/")
    assert close_response.status_code == 200
    listing.refresh_from_db()
    assert listing.status == "closed"


def test_director_cannot_publish_other_directors_listing(api_client):
    owner = _create_director(email="owner@example.ci")
    intruder = _create_director(email="intruder@example.ci")
    listing = _create_listing(owner, status="draft")
    _login(api_client, intruder.email)

    response = api_client.post(f"/api/v1/employment/listings/{listing.id}/publish/")
    assert response.status_code == 404


def test_targeted_teacher_emails_notifies_teachers(api_client):
    director = _create_director()
    teacher = _create_teacher(email="targeted@example.ci")
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/employment/listings/",
        {
            "title": "Prof d'Anglais", "subject": "Anglais", "contract_type": "cdi",
            "description": "...", "city": "Abidjan",
            "targeted_teacher_emails": [teacher.email],
        },
        format="json",
    )
    assert response.status_code == 201
    listing = JobListing.objects.get(title="Prof d'Anglais")
    assert listing.targeted_teachers.filter(id=teacher.id).exists()
    assert Notification.objects.filter(user=teacher, notif_type="new_job_offer").exists()


def test_teacher_applies_to_listing_and_notifies_school(api_client):
    director = _create_director()
    teacher = _create_teacher()
    listing = _create_listing(director, status="active")
    _login(api_client, teacher.email)

    response = api_client.post(
        f"/api/v1/employment/listings/{listing.id}/applications/",
        {"cover_letter": "Je suis motivé."},
        format="json",
    )
    assert response.status_code == 201
    assert JobApplication.objects.filter(listing=listing, teacher=teacher).exists()
    assert Notification.objects.filter(user=director, notif_type="new_job_offer").exists()


def test_teacher_cannot_apply_twice(api_client):
    director = _create_director()
    teacher = _create_teacher()
    listing = _create_listing(director, status="active")
    _login(api_client, teacher.email)

    api_client.post(f"/api/v1/employment/listings/{listing.id}/applications/", {}, format="json")
    second = api_client.post(f"/api/v1/employment/listings/{listing.id}/applications/", {}, format="json")
    assert second.status_code == 400


def test_applications_list_forbidden_for_non_owner(api_client):
    owner = _create_director(email="owner2@example.ci")
    intruder = _create_director(email="intruder2@example.ci")
    listing = _create_listing(owner, status="active")
    _login(api_client, intruder.email)

    response = api_client.get(f"/api/v1/employment/listings/{listing.id}/applications/")
    assert response.status_code == 403


def test_director_marks_application_viewed_and_notifies_teacher(api_client):
    director = _create_director()
    teacher = _create_teacher()
    listing = _create_listing(director, status="active")
    application = JobApplication.objects.create(listing=listing, teacher=teacher)
    _login(api_client, director.email)

    response = api_client.patch(
        f"/api/v1/employment/applications/{application.id}/", {"status": "viewed"}, format="json"
    )
    assert response.status_code == 200
    application.refresh_from_db()
    assert application.status == "viewed"
    assert application.viewed_at is not None
    assert Notification.objects.filter(user=teacher, notif_type="application_viewed").exists()


def test_accepting_application_requires_salary_and_creates_recruitment(api_client):
    director = _create_director()
    teacher = _create_teacher()
    listing = _create_listing(director, status="active")
    application = JobApplication.objects.create(listing=listing, teacher=teacher)
    _login(api_client, director.email)

    missing_salary = api_client.patch(
        f"/api/v1/employment/applications/{application.id}/", {"status": "accepted"}, format="json"
    )
    assert missing_salary.status_code == 400

    response = api_client.patch(
        f"/api/v1/employment/applications/{application.id}/",
        {"status": "accepted", "salary_agreed": 150000},
        format="json",
    )
    assert response.status_code == 200
    assert Recruitment.objects.filter(teacher=teacher, school=director, salary_agreed=150000).exists()
    assert Notification.objects.filter(user=teacher, notif_type="recruitment").exists()


def test_my_applications_and_my_recruitments(api_client):
    director = _create_director()
    teacher = _create_teacher()
    listing = _create_listing(director, status="active")
    JobApplication.objects.create(listing=listing, teacher=teacher)
    Recruitment.objects.create(school=director, teacher=teacher, salary_agreed=100000)
    _login(api_client, teacher.email)

    applications_response = api_client.get("/api/v1/employment/my-applications/")
    assert applications_response.status_code == 200
    assert len(applications_response.data) == 1

    recruitments_response = api_client.get("/api/v1/employment/my-recruitments/")
    assert recruitments_response.status_code == 200
    assert len(recruitments_response.data) == 1


def test_job_seeking_request_forbidden_for_non_gold_teacher(api_client):
    teacher = _create_teacher(email="bronze@example.ci")
    _login(api_client, teacher.email)

    response = api_client.post(
        "/api/v1/employment/job-seeking-requests/", {"message": "Je cherche un poste."}, format="json"
    )
    assert response.status_code == 403


def test_job_seeking_request_allowed_for_gold_teacher(api_client):
    teacher = _make_gold_teacher()
    _login(api_client, teacher.email)

    response = api_client.post(
        "/api/v1/employment/job-seeking-requests/",
        {"message": "Disponible immédiatement.", "city": "Abidjan"},
        format="json",
    )
    assert response.status_code == 201
    assert JobSeekingRequest.objects.filter(teacher=teacher, is_active=True).exists()


def test_new_job_seeking_request_deactivates_previous(api_client):
    teacher = _make_gold_teacher(email="gold.repeat@example.ci")
    _login(api_client, teacher.email)

    first = api_client.post(
        "/api/v1/employment/job-seeking-requests/", {"message": "Premier."}, format="json"
    )
    assert first.status_code == 201
    second = api_client.post(
        "/api/v1/employment/job-seeking-requests/", {"message": "Second."}, format="json"
    )
    assert second.status_code == 201

    active = JobSeekingRequest.objects.filter(teacher=teacher, is_active=True)
    assert active.count() == 1
    assert active.first().message == "Second."


def test_job_seeking_requests_list_is_public(api_client):
    teacher = _make_gold_teacher(email="gold.public@example.ci")
    JobSeekingRequest.objects.create(teacher=teacher, message="Dispo.", city="Abidjan")

    response = api_client.get("/api/v1/employment/job-seeking-requests/")
    assert response.status_code == 200
    assert len(response.data) == 1


def test_my_job_seeking_request_get_and_delete(api_client):
    teacher = _make_gold_teacher(email="gold.mine@example.ci")
    JobSeekingRequest.objects.create(teacher=teacher, message="Dispo.")
    _login(api_client, teacher.email)

    get_response = api_client.get("/api/v1/employment/my-job-seeking-request/")
    assert get_response.status_code == 200
    assert get_response.data["message"] == "Dispo."

    delete_response = api_client.delete("/api/v1/employment/my-job-seeking-request/")
    assert delete_response.status_code == 204
    assert not JobSeekingRequest.objects.filter(teacher=teacher, is_active=True).exists()
