import datetime

import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, Enrollment, SchoolClass, Track
from apps.internships.models import (
    InternshipApplication,
    InternshipConvention,
    InternshipEvaluation,
    InternshipJournal,
    InternshipOffer,
)
from apps.notifications.models import Notification
from apps.users.models import Child, CompanyProfile, DirectorProfile, ParentProfile, User, UserRole

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


def _create_company(email="company@example.ci", company_name="Entreprise Test"):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="C", last_name="O",
        primary_role=UserRole.COMPANY,
    )
    CompanyProfile.objects.create(user=user, company_name=company_name, address="Plateau")
    return user


def _create_enrolled_child(director, child_name="Aicha", school_year="2025-2026"):
    parent_user = User.objects.create_user(
        email=f"parent.{child_name}.{director.id}@example.ci", password="testpass123",
        first_name="P", last_name="A", primary_role=UserRole.PARENT,
    )
    parent_profile = ParentProfile.objects.create(user=parent_user, location="Cocody")
    child = Child.objects.create(parent=parent_profile, first_name=child_name, class_level="3eme")

    department = Department.objects.create(establishment=director.director_profile, name=f"Dept-{child_name}")
    track = Track.objects.create(department=department, name=f"Track-{child_name}")
    school_class = SchoolClass.objects.create(track=track, name="3eme A", school_year=school_year)
    Enrollment.objects.create(child=child, school_class=school_class, status="active")
    return child


def _login(api_client, email, password="testpass123"):
    login = api_client.post("/api/v1/auth/token/", {"email": email, "password": password}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")


def _create_offer(company, **kwargs):
    defaults = {
        "company": company, "title": "Stage développeur", "domain": "Informatique",
        "missions": "Développement web.", "level": "3e", "duration_weeks": 4,
        "period_start": datetime.date.today(), "period_end": datetime.date.today() + datetime.timedelta(weeks=4),
        "city": "Abidjan",
    }
    defaults.update(kwargs)
    return InternshipOffer.objects.create(**defaults)


def test_offer_list_is_public_and_excludes_inactive(api_client):
    company = _create_company()
    _create_offer(company, title="Actif", is_active=True)
    _create_offer(company, title="Inactif", is_active=False)

    response = api_client.get("/api/v1/internships/offers/")
    assert response.status_code == 200
    titles = [r["title"] for r in response.data]
    assert "Actif" in titles
    assert "Inactif" not in titles


def test_offer_create_forbidden_for_director(api_client):
    director = _create_director()
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/internships/offers/",
        {
            "title": "X", "domain": "Info", "missions": "...", "level": "3e",
            "duration_weeks": 4, "period_start": "2026-01-01", "period_end": "2026-02-01",
            "city": "Abidjan",
        },
        format="json",
    )
    assert response.status_code == 403


def test_company_creates_offer(api_client):
    company = _create_company()
    _login(api_client, company.email)

    response = api_client.post(
        "/api/v1/internships/offers/",
        {
            "title": "Stage Marketing", "domain": "Marketing", "missions": "Réseaux sociaux.",
            "level": "terminale", "duration_weeks": 8,
            "period_start": "2026-01-01", "period_end": "2026-03-01", "city": "Abidjan",
        },
        format="json",
    )
    assert response.status_code == 201
    assert InternshipOffer.objects.filter(title="Stage Marketing", company=company).exists()


def test_company_list_shows_own_inactive_offers(api_client):
    company = _create_company()
    other = _create_company(email="other.company@example.ci")
    _create_offer(company, title="Mon inactif", is_active=False)
    _create_offer(other, title="Offre concurrente", is_active=True)
    _login(api_client, company.email)

    response = api_client.get("/api/v1/internships/offers/")
    titles = [r["title"] for r in response.data]
    assert "Mon inactif" in titles
    assert "Offre concurrente" not in titles


def test_director_applies_on_behalf_of_enrolled_child(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    _login(api_client, director.email)

    response = api_client.post(
        f"/api/v1/internships/offers/{offer.id}/applications/",
        {"student_id": child.id, "motivation": "Motivé."},
        format="json",
    )
    assert response.status_code == 201
    assert InternshipApplication.objects.filter(offer=offer, student=child).exists()
    assert Notification.objects.filter(user=company, notif_type="stage_update").exists()


def test_director_cannot_apply_for_child_not_enrolled_in_own_establishment(api_client):
    director = _create_director(email="dirA@example.ci")
    other_director = _create_director(email="dirB@example.ci")
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(other_director)
    _login(api_client, director.email)

    response = api_client.post(
        f"/api/v1/internships/offers/{offer.id}/applications/",
        {"student_id": child.id},
        format="json",
    )
    assert response.status_code == 403


def test_cannot_apply_twice_for_same_child_and_offer(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    _login(api_client, director.email)

    api_client.post(f"/api/v1/internships/offers/{offer.id}/applications/", {"student_id": child.id}, format="json")
    second = api_client.post(
        f"/api/v1/internships/offers/{offer.id}/applications/", {"student_id": child.id}, format="json"
    )
    assert second.status_code == 400


def test_applications_list_forbidden_for_non_owner_company(api_client):
    company = _create_company()
    intruder = _create_company(email="intruder@example.ci")
    offer = _create_offer(company)
    _login(api_client, intruder.email)

    response = api_client.get(f"/api/v1/internships/offers/{offer.id}/applications/")
    assert response.status_code == 403


def test_company_accepts_application_creates_convention_and_notifies(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    _login(api_client, company.email)

    response = api_client.patch(
        f"/api/v1/internships/applications/{application.id}/", {"status": "accepted"}, format="json"
    )
    assert response.status_code == 200
    application.refresh_from_db()
    assert application.status == "accepted"
    assert InternshipConvention.objects.filter(application=application).exists()
    assert Notification.objects.filter(user=director, notif_type="stage_update").exists()


def test_company_rejects_application(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    _login(api_client, company.email)

    response = api_client.patch(
        f"/api/v1/internships/applications/{application.id}/", {"status": "rejected"}, format="json"
    )
    assert response.status_code == 200
    application.refresh_from_db()
    assert application.status == "rejected"
    assert not InternshipConvention.objects.filter(application=application).exists()


def test_my_applications_and_my_conventions(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    InternshipConvention.objects.create(application=application)
    _login(api_client, director.email)

    applications_response = api_client.get("/api/v1/internships/my-applications/")
    assert applications_response.status_code == 200
    assert len(applications_response.data) == 1

    conventions_response = api_client.get("/api/v1/internships/my-conventions/")
    assert conventions_response.status_code == 200
    assert len(conventions_response.data) == 1


def test_sign_convention_by_both_parties_marks_complete(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    convention = InternshipConvention.objects.create(application=application)

    _login(api_client, director.email)
    first = api_client.post(f"/api/v1/internships/conventions/{convention.id}/sign/")
    assert first.status_code == 200
    assert first.data["status"] == "signed_sch"

    _login(api_client, company.email)
    second = api_client.post(f"/api/v1/internships/conventions/{convention.id}/sign/")
    assert second.status_code == 200
    assert second.data["status"] == "complete"


def test_sign_convention_forbidden_for_non_party(api_client):
    director = _create_director()
    company = _create_company()
    intruder = _create_company(email="intruder.sign@example.ci")
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    convention = InternshipConvention.objects.create(application=application)
    _login(api_client, intruder.email)

    response = api_client.post(f"/api/v1/internships/conventions/{convention.id}/sign/")
    assert response.status_code == 403


def test_company_adds_journal_entry_readable_by_school(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    convention = InternshipConvention.objects.create(application=application)

    _login(api_client, company.email)
    create_response = api_client.post(
        f"/api/v1/internships/conventions/{convention.id}/journal/",
        {"date": "2026-02-01", "content": "Premier jour, découverte de l'équipe."},
        format="json",
    )
    assert create_response.status_code == 201
    assert InternshipJournal.objects.filter(convention=convention).exists()

    _login(api_client, director.email)
    list_response = api_client.get(f"/api/v1/internships/conventions/{convention.id}/journal/")
    assert list_response.status_code == 200
    assert len(list_response.data) == 1


def test_school_cannot_add_journal_entry(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    convention = InternshipConvention.objects.create(application=application)
    _login(api_client, director.email)

    response = api_client.post(
        f"/api/v1/internships/conventions/{convention.id}/journal/",
        {"date": "2026-02-01", "content": "..."},
        format="json",
    )
    assert response.status_code == 403


def test_company_evaluates_student_and_notifies_school(api_client):
    director = _create_director()
    company = _create_company()
    offer = _create_offer(company)
    child = _create_enrolled_child(director)
    application = InternshipApplication.objects.create(offer=offer, school=director, student=child)
    convention = InternshipConvention.objects.create(application=application)
    _login(api_client, company.email)

    response = api_client.post(
        f"/api/v1/internships/conventions/{convention.id}/evaluations/",
        {
            "punctuality": 4, "initiative": 5, "integration": 4, "skills": 4,
            "global_rating": 4, "comment": "Très bien.",
        },
        format="json",
    )
    assert response.status_code == 201
    evaluation = InternshipEvaluation.objects.get(convention=convention)
    assert evaluation.evaluator_type == "company"
    assert Notification.objects.filter(user=director, notif_type="stage_update").exists()
