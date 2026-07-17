import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, SchoolClass, Subject, Track
from apps.library.models import LibraryResource, ResourceFavorite
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


def _create_affiliated_teacher(profile, email, school_year="2025-2026"):
    teacher = _create_teacher(email=email)
    department = Department.objects.create(establishment=profile, name=f"Dept-{email}")
    track = Track.objects.create(department=department, name=f"Track-{email}")
    school_class = SchoolClass.objects.create(track=track, name="Classe", school_year=school_year)
    Subject.objects.create(school_class=school_class, name="Matière", teacher=teacher)
    return teacher


def _create_resource(establishment, author=None, **kwargs):
    defaults = {
        "title": "Cours de maths",
        "resource_type": "course",
        "level": "tle",
        "subject": "Mathématiques",
        "file_url": "https://example.ci/cours.pdf",
    }
    defaults.update(kwargs)
    return LibraryResource.objects.create(establishment=establishment, author=author, **defaults)


def test_resources_require_authentication(api_client):
    _, profile = _create_director(email="dir.auth@example.ci")
    response = api_client.get(f"/api/v1/library/establishments/{profile.id}/resources/")
    assert response.status_code == 401


def test_resources_forbidden_for_unaffiliated_teacher(api_client):
    _, profile = _create_director(email="dir.forbidden@example.ci")
    outsider = _create_teacher(email="outsider@example.ci")
    _login(api_client, outsider.email)

    response = api_client.get(f"/api/v1/library/establishments/{profile.id}/resources/")
    assert response.status_code == 403


def test_director_lists_own_establishment_resources(api_client):
    director, profile = _create_director(email="dir.list@example.ci")
    _create_resource(profile, title="Cours A")
    _create_resource(profile, title="Cours B")
    _login(api_client, director.email)

    response = api_client.get(f"/api/v1/library/establishments/{profile.id}/resources/")
    assert response.status_code == 200
    assert len(response.data) == 2


def test_affiliated_teacher_can_list_and_create_resource(api_client):
    _, profile = _create_director(email="dir.affiliated@example.ci")
    teacher = _create_affiliated_teacher(profile, "affiliated.teacher@example.ci")
    _login(api_client, teacher.email)

    response = api_client.post(
        f"/api/v1/library/establishments/{profile.id}/resources/",
        {
            "title": "Annale BAC 2025", "resource_type": "exam", "level": "tle",
            "subject": "Physique", "file_url": "https://example.ci/annale.pdf",
        },
        format="json",
    )
    assert response.status_code == 201
    resource = LibraryResource.objects.get(title="Annale BAC 2025")
    assert resource.establishment == profile
    assert resource.author == teacher
    assert resource.is_contributed is True
    assert response.data["author_name"] == teacher.get_full_name()


def test_resource_list_filters_by_subject_and_level(api_client):
    director, profile = _create_director(email="dir.filter@example.ci")
    _create_resource(profile, title="Maths Tle", subject="Mathématiques", level="tle")
    _create_resource(profile, title="Maths 3e", subject="Mathématiques", level="3e")
    _create_resource(profile, title="SVT Tle", subject="SVT", level="tle")
    _login(api_client, director.email)

    response = api_client.get(
        f"/api/v1/library/establishments/{profile.id}/resources/",
        {"subject": "Mathématiques", "level": "tle"},
    )
    assert response.status_code == 200
    titles = [r["title"] for r in response.data]
    assert titles == ["Maths Tle"]


def test_archived_resources_excluded_from_list(api_client):
    director, profile = _create_director(email="dir.archived@example.ci")
    _create_resource(profile, title="Visible")
    _create_resource(profile, title="Archivée", is_archived=True)
    _login(api_client, director.email)

    response = api_client.get(f"/api/v1/library/establishments/{profile.id}/resources/")
    titles = [r["title"] for r in response.data]
    assert "Visible" in titles
    assert "Archivée" not in titles


def test_resource_detail_forbidden_for_unaffiliated_user(api_client):
    _, profile = _create_director(email="dir.detailforbidden@example.ci")
    resource = _create_resource(profile)
    outsider = _create_teacher(email="outsider.detail@example.ci")
    _login(api_client, outsider.email)

    response = api_client.get(f"/api/v1/library/resources/{resource.id}/")
    assert response.status_code == 403


def test_resource_update_forbidden_for_non_author_non_director(api_client):
    _, profile = _create_director(email="dir.updateforbidden@example.ci")
    author = _create_affiliated_teacher(profile, "author.update@example.ci")
    other_teacher = _create_affiliated_teacher(profile, "other.update@example.ci", school_year="2024-2025")
    resource = _create_resource(profile, author=author)
    _login(api_client, other_teacher.email)

    response = api_client.patch(
        f"/api/v1/library/resources/{resource.id}/", {"is_archived": True}, format="json"
    )
    assert response.status_code == 403


def test_resource_update_allowed_for_author(api_client):
    _, profile = _create_director(email="dir.updateauthor@example.ci")
    author = _create_affiliated_teacher(profile, "author.self@example.ci")
    resource = _create_resource(profile, author=author)
    _login(api_client, author.email)

    response = api_client.patch(
        f"/api/v1/library/resources/{resource.id}/", {"is_archived": True}, format="json"
    )
    assert response.status_code == 200
    resource.refresh_from_db()
    assert resource.is_archived is True


def test_resource_update_allowed_for_director(api_client):
    director, profile = _create_director(email="dir.updateself@example.ci")
    author = _create_affiliated_teacher(profile, "author.fordirector@example.ci")
    resource = _create_resource(profile, author=author)
    _login(api_client, director.email)

    response = api_client.patch(
        f"/api/v1/library/resources/{resource.id}/", {"is_archived": True}, format="json"
    )
    assert response.status_code == 200


def test_download_increments_counter_and_logs(api_client):
    from apps.library.models import ResourceDownload

    director, profile = _create_director(email="dir.download@example.ci")
    resource = _create_resource(profile)
    _login(api_client, director.email)

    response = api_client.post(f"/api/v1/library/resources/{resource.id}/download/")
    assert response.status_code == 200
    assert response.data["download_count"] == 1
    resource.refresh_from_db()
    assert resource.download_count == 1
    assert ResourceDownload.objects.filter(resource=resource, user=director).exists()


def test_favorite_and_unfavorite_resource(api_client):
    director, profile = _create_director(email="dir.favorite@example.ci")
    resource = _create_resource(profile)
    _login(api_client, director.email)

    add_response = api_client.post(f"/api/v1/library/resources/{resource.id}/favorite/")
    assert add_response.status_code == 201
    assert ResourceFavorite.objects.filter(resource=resource, user=director).exists()

    remove_response = api_client.delete(f"/api/v1/library/resources/{resource.id}/favorite/")
    assert remove_response.status_code == 204
    assert not ResourceFavorite.objects.filter(resource=resource, user=director).exists()


def test_my_favorites_lists_only_favorited_resources(api_client):
    director, profile = _create_director(email="dir.myfavorites@example.ci")
    favorited = _create_resource(profile, title="Favorite")
    _create_resource(profile, title="Not favorited")
    ResourceFavorite.objects.create(user=director, resource=favorited)
    _login(api_client, director.email)

    response = api_client.get("/api/v1/library/my-favorites/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["title"] == "Favorite"
    assert response.data[0]["is_favorited"] is True


def test_my_establishments_lists_director_and_affiliated_teacher(api_client):
    director, profile = _create_director(email="dir.myestablishments@example.ci")
    teacher = _create_affiliated_teacher(profile, "teacher.myestablishments@example.ci")

    _login(api_client, director.email)
    director_response = api_client.get("/api/v1/library/my-establishments/")
    assert director_response.status_code == 200
    assert [e["id"] for e in director_response.data] == [profile.id]

    _login(api_client, teacher.email)
    teacher_response = api_client.get("/api/v1/library/my-establishments/")
    assert teacher_response.status_code == 200
    assert [e["id"] for e in teacher_response.data] == [profile.id]


def test_my_establishments_empty_for_unaffiliated_teacher(api_client):
    teacher = _create_teacher(email="unaffiliated@example.ci")
    _login(api_client, teacher.email)

    response = api_client.get("/api/v1/library/my-establishments/")
    assert response.status_code == 200
    assert response.data == []
