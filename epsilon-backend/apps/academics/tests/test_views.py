import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, SchoolClass, Subject, Track
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


def _create_class(school_year="2025-2026", homeroom_teacher=None):
    director, profile = _create_director(email=f"dir.class.{school_year}@example.ci")
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    school_class = SchoolClass.objects.create(
        track=track, name="Terminale D1", school_year=school_year, homeroom_teacher=homeroom_teacher
    )
    return director, school_class


def test_subjects_require_authentication(api_client):
    titulaire = _create_teacher(email="titulaire.auth@example.ci")
    _, school_class = _create_class(school_year="2020-2021", homeroom_teacher=titulaire)
    response = api_client.get(f"/api/v1/academics/classes/{school_class.id}/subjects/")
    assert response.status_code == 401


def test_subjects_forbidden_for_non_homeroom_teacher(api_client):
    titulaire = _create_teacher(email="titulaire.other@example.ci")
    other_teacher = _create_teacher(email="not.titulaire@example.ci")
    _, school_class = _create_class(school_year="2020-2022", homeroom_teacher=titulaire)

    _login(api_client, other_teacher.email)
    response = api_client.get(f"/api/v1/academics/classes/{school_class.id}/subjects/")
    assert response.status_code == 403


def test_homeroom_teacher_creates_subject_without_dedicated_teacher(api_client):
    titulaire = _create_teacher(email="titulaire.create@example.ci")
    _, school_class = _create_class(school_year="2020-2023", homeroom_teacher=titulaire)
    _login(api_client, titulaire.email)

    response = api_client.post(
        f"/api/v1/academics/classes/{school_class.id}/subjects/",
        {"name": "Mathématiques"},
        format="json",
    )
    assert response.status_code == 201
    assert Subject.objects.filter(name="Mathématiques", school_class=school_class).exists()
    assert response.data["teacher"] is None


def test_homeroom_teacher_creates_subject_and_notifies_dedicated_teacher(api_client):
    titulaire = _create_teacher(email="titulaire.notify@example.ci")
    dedicated = _create_teacher(email="dedicated.notify@example.ci")
    _, school_class = _create_class(school_year="2020-2024", homeroom_teacher=titulaire)
    _login(api_client, titulaire.email)

    response = api_client.post(
        f"/api/v1/academics/classes/{school_class.id}/subjects/",
        {"name": "Physique-Chimie", "teacher_email": dedicated.email},
        format="json",
    )
    assert response.status_code == 201
    subject = Subject.objects.get(name="Physique-Chimie")
    assert subject.teacher == dedicated
    assert response.data["teacher"]["email"] == dedicated.email
    assert response.data["school_class"]["name"] == school_class.name
    assert Notification.objects.filter(user=dedicated, notif_type="class_assignment").exists()


def test_subject_dedicated_teacher_must_have_teacher_role(api_client):
    titulaire = _create_teacher(email="titulaire.wrongrole@example.ci")
    parent = User.objects.create_user(
        email="parent.subject@example.ci", password="testpass123", first_name="P", last_name="A",
        primary_role=UserRole.PARENT,
    )
    _, school_class = _create_class(school_year="2020-2025", homeroom_teacher=titulaire)
    _login(api_client, titulaire.email)

    response = api_client.post(
        f"/api/v1/academics/classes/{school_class.id}/subjects/",
        {"name": "SVT", "teacher_email": parent.email},
        format="json",
    )
    assert response.status_code == 400


def test_homeroom_teacher_reassigns_dedicated_teacher_and_notifies_new_teacher(api_client):
    titulaire = _create_teacher(email="titulaire.reassign@example.ci")
    first_teacher = _create_teacher(email="first.reassign@example.ci")
    second_teacher = _create_teacher(email="second.reassign@example.ci")
    _, school_class = _create_class(school_year="2020-2026", homeroom_teacher=titulaire)
    subject = Subject.objects.create(school_class=school_class, name="Français", teacher=first_teacher)
    _login(api_client, titulaire.email)

    response = api_client.patch(
        f"/api/v1/academics/subjects/{subject.id}/",
        {"teacher_email": second_teacher.email},
        format="json",
    )
    assert response.status_code == 200
    subject.refresh_from_db()
    assert subject.teacher == second_teacher
    assert Notification.objects.filter(user=second_teacher, notif_type="class_assignment").exists()
    assert not Notification.objects.filter(user=first_teacher, notif_type="class_assignment").exists()


def test_subject_detail_forbidden_for_non_owner_homeroom_teacher(api_client):
    titulaire = _create_teacher(email="titulaire.detailowner@example.ci")
    intruder = _create_teacher(email="intruder.detail@example.ci")
    _, school_class = _create_class(school_year="2020-2027", homeroom_teacher=titulaire)
    subject = Subject.objects.create(school_class=school_class, name="Anglais")

    _login(api_client, intruder.email)
    response = api_client.get(f"/api/v1/academics/subjects/{subject.id}/")
    assert response.status_code == 404


def test_my_dedicated_subjects_lists_only_assigned_subjects(api_client):
    titulaire = _create_teacher(email="titulaire.mysubjects@example.ci")
    dedicated = _create_teacher(email="dedicated.mysubjects@example.ci")
    other_dedicated = _create_teacher(email="other.mysubjects@example.ci")
    _, school_class = _create_class(school_year="2020-2028", homeroom_teacher=titulaire)
    Subject.objects.create(school_class=school_class, name="Maths", teacher=dedicated)
    Subject.objects.create(school_class=school_class, name="SVT", teacher=other_dedicated)

    _login(api_client, dedicated.email)
    response = api_client.get("/api/v1/academics/my-subjects/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["name"] == "Maths"
    assert response.data[0]["school_class"]["name"] == school_class.name


def test_my_dedicated_subjects_forbidden_for_non_teacher(api_client):
    director, _ = _create_director(email="dir.mysubjectsforbidden@example.ci")
    _login(api_client, director.email)
    response = api_client.get("/api/v1/academics/my-subjects/")
    assert response.status_code == 403
