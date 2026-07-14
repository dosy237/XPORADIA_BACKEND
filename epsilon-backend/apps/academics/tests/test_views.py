import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, SchoolClass, Track
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
    profile = DirectorProfile.objects.create(user=user, school_name=school_name, address="Cocody")
    return user, profile


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


def test_departments_require_authentication(api_client):
    response = api_client.get("/api/v1/academics/departments/")
    assert response.status_code == 401


def test_departments_forbidden_for_non_director(api_client):
    teacher = _create_teacher()
    _login(api_client, teacher.email)
    response = api_client.get("/api/v1/academics/departments/")
    assert response.status_code == 403


def test_director_creates_department(api_client):
    director, _ = _create_director()
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/academics/departments/", {"name": "Secondaire", "description": "Collège et lycée"}, format="json"
    )
    assert response.status_code == 201
    assert Department.objects.filter(name="Secondaire", establishment__user=director).exists()


def test_departments_isolated_between_establishments(api_client):
    director1, profile1 = _create_director(email="dir1@example.ci", school_name="École 1")
    director2, _ = _create_director(email="dir2@example.ci", school_name="École 2")
    Department.objects.create(establishment=profile1, name="Primaire")

    _login(api_client, director2.email)
    response = api_client.get("/api/v1/academics/departments/")
    assert response.status_code == 200
    assert response.data == []


def test_director_creates_track_under_own_department(api_client):
    director, profile = _create_director()
    department = Department.objects.create(establishment=profile, name="Secondaire")
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/academics/tracks/",
        {"name": "Scientifique", "department_id": department.id},
        format="json",
    )
    assert response.status_code == 201
    assert Track.objects.filter(name="Scientifique", department=department).exists()


def test_director_cannot_create_track_under_other_establishment_department(api_client):
    _, profile1 = _create_director(email="dir1@example.ci", school_name="École 1")
    director2, _ = _create_director(email="dir2@example.ci", school_name="École 2")
    other_department = Department.objects.create(establishment=profile1, name="Secondaire")

    _login(api_client, director2.email)
    response = api_client.post(
        "/api/v1/academics/tracks/",
        {"name": "Scientifique", "department_id": other_department.id},
        format="json",
    )
    assert response.status_code == 403


def test_director_creates_class_with_homeroom_teacher(api_client):
    director, profile = _create_director()
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    teacher = _create_teacher()
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/academics/classes/",
        {
            "track_id": track.id, "name": "Terminale D1", "school_year": "2025-2026",
            "homeroom_teacher_email": teacher.email, "capacity": 40,
        },
        format="json",
    )
    assert response.status_code == 201
    school_class = SchoolClass.objects.get(name="Terminale D1")
    assert school_class.homeroom_teacher == teacher
    assert response.data["homeroom_teacher"]["email"] == teacher.email


def test_class_homeroom_teacher_must_have_teacher_role(api_client):
    director, profile = _create_director()
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    parent = User.objects.create_user(
        email="parent@example.ci", password="testpass123", first_name="P", last_name="A",
        primary_role=UserRole.PARENT,
    )
    _login(api_client, director.email)

    response = api_client.post(
        "/api/v1/academics/classes/",
        {
            "track_id": track.id, "name": "Terminale D1", "school_year": "2025-2026",
            "homeroom_teacher_email": parent.email,
        },
        format="json",
    )
    assert response.status_code == 400


def test_director_cannot_create_class_under_other_establishment_track(api_client):
    _, profile1 = _create_director(email="dir1@example.ci", school_name="École 1")
    director2, _ = _create_director(email="dir2@example.ci", school_name="École 2")
    department = Department.objects.create(establishment=profile1, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")

    _login(api_client, director2.email)
    response = api_client.post(
        "/api/v1/academics/classes/",
        {"track_id": track.id, "name": "Terminale D1", "school_year": "2025-2026"},
        format="json",
    )
    assert response.status_code == 403


def test_my_homeroom_classes_requires_authentication(api_client):
    response = api_client.get("/api/v1/academics/my-classes/")
    assert response.status_code == 401


def test_my_homeroom_classes_forbidden_for_non_teacher(api_client):
    director, _ = _create_director()
    _login(api_client, director.email)
    response = api_client.get("/api/v1/academics/my-classes/")
    assert response.status_code == 403


def test_my_homeroom_classes_lists_only_own_classes(api_client):
    director, profile = _create_director()
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    teacher = _create_teacher()
    other_teacher = _create_teacher(email="other.teacher@example.ci")
    SchoolClass.objects.create(
        track=track, name="Terminale D1", school_year="2025-2026", homeroom_teacher=teacher
    )
    SchoolClass.objects.create(
        track=track, name="Terminale D2", school_year="2025-2026", homeroom_teacher=other_teacher
    )

    _login(api_client, teacher.email)
    response = api_client.get("/api/v1/academics/my-classes/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["name"] == "Terminale D1"
    # Le track ET son département doivent être imbriqués en profondeur —
    # pas de simples ID — pour que le frontend puisse afficher le fil
    # d'ariane classe → filière → département sans requête supplémentaire.
    assert response.data[0]["track"]["name"] == "Scientifique"
    assert response.data[0]["track"]["department"]["name"] == "Secondaire"


def test_class_unique_together_track_name_year(api_client):
    director, profile = _create_director()
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    _login(api_client, director.email)

    payload = {"track_id": track.id, "name": "Terminale D1", "school_year": "2025-2026"}
    first = api_client.post("/api/v1/academics/classes/", payload, format="json")
    assert first.status_code == 201
    second = api_client.post("/api/v1/academics/classes/", payload, format="json")
    assert second.status_code == 400
