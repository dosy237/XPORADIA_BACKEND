import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, SchoolClass, Subject, Track
from apps.users.models import DirectorProfile, TeacherProfile, User, UserRole
from apps.virtual_classes.models import Exercise, VirtualClass

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


def _create_teacher(email):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="T", last_name="E",
        primary_role=UserRole.TEACHER,
    )
    TeacherProfile.objects.create(user=user)
    return user


def _login(api_client, email, password="testpass123"):
    login = api_client.post("/api/v1/auth/token/", {"email": email, "password": password}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")


def _create_subject(name, homeroom_teacher=None, dedicated_teacher=None, school_year="2025-2026"):
    director_user = User.objects.create_user(
        email=f"dir.{name}.{school_year}@example.ci", password="testpass123",
        first_name="D", last_name="R", primary_role=UserRole.DIRECTOR,
    )
    profile = DirectorProfile.objects.create(user=director_user, school_name="École Test", address="Cocody")
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    school_class = SchoolClass.objects.create(
        track=track, name="Terminale D1", school_year=school_year, homeroom_teacher=homeroom_teacher
    )
    return Subject.objects.create(school_class=school_class, name=name, teacher=dedicated_teacher)


def test_virtual_class_auto_created_when_subject_created():
    teacher = _create_teacher("auto.dedicated@example.ci")
    subject = _create_subject("Maths Auto", dedicated_teacher=teacher, school_year="2030-2031")
    assert VirtualClass.objects.filter(subject=subject).exists()


def test_subject_virtual_class_requires_authentication(api_client):
    subject = _create_subject("Maths Auth", school_year="2030-2032")
    response = api_client.get(f"/api/v1/virtual-classes/subjects/{subject.id}/")
    assert response.status_code == 401


def test_subject_virtual_class_forbidden_for_unrelated_teacher(api_client):
    intruder = _create_teacher("intruder.vc@example.ci")
    subject = _create_subject("Maths Forbidden", school_year="2030-2033")

    _login(api_client, intruder.email)
    response = api_client.get(f"/api/v1/virtual-classes/subjects/{subject.id}/")
    assert response.status_code == 403


def test_dedicated_teacher_can_view_virtual_class(api_client):
    dedicated = _create_teacher("dedicated.view@example.ci")
    subject = _create_subject("Physique", dedicated_teacher=dedicated, school_year="2030-2034")

    _login(api_client, dedicated.email)
    response = api_client.get(f"/api/v1/virtual-classes/subjects/{subject.id}/")
    assert response.status_code == 200
    assert response.data["subject_name"] == "Physique"
    assert response.data["school_class_name"] == "Terminale D1"


def test_homeroom_teacher_can_view_but_not_edit_virtual_class(api_client):
    titulaire = _create_teacher("titulaire.view@example.ci")
    dedicated = _create_teacher("dedicated.foredit@example.ci")
    subject = _create_subject(
        "SVT", homeroom_teacher=titulaire, dedicated_teacher=dedicated, school_year="2030-2035"
    )

    _login(api_client, titulaire.email)
    get_response = api_client.get(f"/api/v1/virtual-classes/subjects/{subject.id}/")
    assert get_response.status_code == 200

    patch_response = api_client.patch(
        f"/api/v1/virtual-classes/subjects/{subject.id}/",
        {"description": "Bienvenue !"},
        format="json",
    )
    assert patch_response.status_code == 403


def test_dedicated_teacher_can_update_virtual_class_description(api_client):
    dedicated = _create_teacher("dedicated.edit@example.ci")
    subject = _create_subject("Français", dedicated_teacher=dedicated, school_year="2030-2036")

    _login(api_client, dedicated.email)
    response = api_client.patch(
        f"/api/v1/virtual-classes/subjects/{subject.id}/",
        {"description": "Bienvenue dans le cours de français."},
        format="json",
    )
    assert response.status_code == 200
    assert VirtualClass.objects.get(subject=subject).description == "Bienvenue dans le cours de français."


def test_dedicated_teacher_creates_exercise(api_client):
    dedicated = _create_teacher("dedicated.exercise@example.ci")
    subject = _create_subject("Anglais", dedicated_teacher=dedicated, school_year="2030-2037")

    _login(api_client, dedicated.email)
    response = api_client.post(
        f"/api/v1/virtual-classes/subjects/{subject.id}/exercises/",
        {"title": "Devoir 1", "instructions": "Faire les exercices p.12"},
        format="json",
    )
    assert response.status_code == 201
    assert Exercise.objects.filter(title="Devoir 1", virtual_class__subject=subject).exists()
    assert response.data["status"] == "draft"
    assert response.data["published_at"] is None


def test_exercise_creation_forbidden_for_non_dedicated_teacher(api_client):
    titulaire = _create_teacher("titulaire.noexercise@example.ci")
    dedicated = _create_teacher("dedicated.other@example.ci")
    subject = _create_subject(
        "Histoire", homeroom_teacher=titulaire, dedicated_teacher=dedicated, school_year="2030-2038"
    )

    _login(api_client, titulaire.email)
    response = api_client.post(
        f"/api/v1/virtual-classes/subjects/{subject.id}/exercises/",
        {"title": "Devoir 1", "instructions": "..."},
        format="json",
    )
    assert response.status_code == 403


def test_publishing_exercise_sets_published_at(api_client):
    dedicated = _create_teacher("dedicated.publish@example.ci")
    subject = _create_subject("Géographie", dedicated_teacher=dedicated, school_year="2030-2039")

    _login(api_client, dedicated.email)
    response = api_client.post(
        f"/api/v1/virtual-classes/subjects/{subject.id}/exercises/",
        {"title": "Devoir 2", "instructions": "...", "status": "published"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["published_at"] is not None


def test_homeroom_teacher_lists_exercises_but_cannot_create(api_client):
    titulaire = _create_teacher("titulaire.list@example.ci")
    dedicated = _create_teacher("dedicated.list@example.ci")
    subject = _create_subject(
        "Chimie", homeroom_teacher=titulaire, dedicated_teacher=dedicated, school_year="2030-2040"
    )
    virtual_class = VirtualClass.objects.get(subject=subject)
    Exercise.objects.create(virtual_class=virtual_class, title="Devoir existant", instructions="...")

    _login(api_client, titulaire.email)
    response = api_client.get(f"/api/v1/virtual-classes/subjects/{subject.id}/exercises/")
    assert response.status_code == 200
    assert len(response.data) == 1


def test_exercise_detail_forbidden_for_unrelated_teacher(api_client):
    intruder = _create_teacher("intruder.detail@example.ci")
    dedicated = _create_teacher("dedicated.detail@example.ci")
    subject = _create_subject("SES", dedicated_teacher=dedicated, school_year="2030-2041")
    virtual_class = VirtualClass.objects.get(subject=subject)
    exercise = Exercise.objects.create(virtual_class=virtual_class, title="Devoir", instructions="...")

    _login(api_client, intruder.email)
    response = api_client.get(f"/api/v1/virtual-classes/exercises/{exercise.id}/")
    assert response.status_code == 403


def test_dedicated_teacher_updates_and_deletes_exercise(api_client):
    dedicated = _create_teacher("dedicated.crud@example.ci")
    subject = _create_subject("Philosophie", dedicated_teacher=dedicated, school_year="2030-2042")
    virtual_class = VirtualClass.objects.get(subject=subject)
    exercise = Exercise.objects.create(virtual_class=virtual_class, title="Devoir", instructions="...")

    _login(api_client, dedicated.email)
    update_response = api_client.patch(
        f"/api/v1/virtual-classes/exercises/{exercise.id}/", {"status": "published"}, format="json"
    )
    assert update_response.status_code == 200
    assert update_response.data["published_at"] is not None

    delete_response = api_client.delete(f"/api/v1/virtual-classes/exercises/{exercise.id}/")
    assert delete_response.status_code == 204
    assert not Exercise.objects.filter(id=exercise.id).exists()
