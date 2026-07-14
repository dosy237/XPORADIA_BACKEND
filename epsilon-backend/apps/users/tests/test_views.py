import pytest
from rest_framework.test import APIClient

from apps.users.models import OTPCode, TeacherProfile, User, UserRole

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


def test_director_profile_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/director-profile/")
    assert response.status_code == 401


def test_director_profile_get_and_update(api_client):
    api_client.post(
        "/api/v1/auth/register/director/",
        {
            "email": "directeur.profile@example.ci", "password": "testpass123",
            "first_name": "D", "last_name": "R",
            "school_name": "Ecole Test", "address": "Cocody, Abidjan",
            "levels_taught": ["Primaire"], "student_count": 120,
        },
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/",
        {"email": "directeur.profile@example.ci", "password": "testpass123"},
        format="json",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    get_response = api_client.get("/api/v1/auth/director-profile/")
    assert get_response.status_code == 200
    assert get_response.data["school_name"] == "Ecole Test"
    assert get_response.data["student_count"] == 120

    patch_response = api_client.patch(
        "/api/v1/auth/director-profile/",
        {"student_count": 150, "levels_taught": ["Primaire", "Collège"]},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["student_count"] == 150
    assert patch_response.data["levels_taught"] == ["Primaire", "Collège"]
    # is_partner est en lecture seule : une tentative de le forcer via l'API
    # ne doit jamais accorder le statut de partenaire.
    assert patch_response.data["is_partner"] is False


def test_director_profile_is_partner_is_read_only(api_client):
    api_client.post(
        "/api/v1/auth/register/director/",
        {
            "email": "directeur.ro@example.ci", "password": "testpass123",
            "first_name": "D", "last_name": "R",
            "school_name": "Ecole RO", "address": "Yopougon, Abidjan",
        },
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "directeur.ro@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.patch(
        "/api/v1/auth/director-profile/", {"is_partner": True}, format="json"
    )
    assert response.status_code == 200
    assert response.data["is_partner"] is False


def test_director_profile_forbidden_for_other_roles(api_client):
    api_client.post(
        "/api/v1/auth/register/parent/",
        {"email": "notdirector@example.ci", "password": "testpass123", "first_name": "N", "last_name": "D"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "notdirector@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/auth/director-profile/")
    assert response.status_code == 403


def test_company_profile_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/company-profile/")
    assert response.status_code == 401


def test_company_profile_get_and_update(api_client):
    api_client.post(
        "/api/v1/auth/register/company/",
        {
            "email": "entreprise.profile@example.ci", "password": "testpass123",
            "first_name": "S", "last_name": "K",
            "company_name": "Ivoire Digital", "sector": "EdTech", "address": "Plateau, Abidjan",
        },
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "entreprise.profile@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    get_response = api_client.get("/api/v1/auth/company-profile/")
    assert get_response.status_code == 200
    assert get_response.data["company_name"] == "Ivoire Digital"

    patch_response = api_client.patch(
        "/api/v1/auth/company-profile/", {"sector": "Technologies éducatives"}, format="json"
    )
    assert patch_response.status_code == 200
    assert patch_response.data["sector"] == "Technologies éducatives"
    assert patch_response.data["is_partner"] is False


def test_company_profile_is_partner_is_read_only(api_client):
    api_client.post(
        "/api/v1/auth/register/company/",
        {
            "email": "entreprise.ro@example.ci", "password": "testpass123",
            "first_name": "S", "last_name": "K",
            "company_name": "RO Corp", "address": "Marcory, Abidjan",
        },
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "entreprise.ro@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.patch("/api/v1/auth/company-profile/", {"is_partner": True}, format="json")
    assert response.status_code == 200
    assert response.data["is_partner"] is False


def test_company_profile_forbidden_for_other_roles(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "notcompany@example.ci", "password": "testpass123", "first_name": "N", "last_name": "C"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "notcompany@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/auth/company-profile/")
    assert response.status_code == 403


def _login_parent(api_client, email, children=None):
    api_client.post(
        "/api/v1/auth/register/parent/",
        {
            "email": email, "password": "testpass123",
            "first_name": "F", "last_name": "T", "location": "Marcory, Abidjan",
            "children": children or [],
        },
        format="json",
    )
    login = api_client.post("/api/v1/auth/token/", {"email": email, "password": "testpass123"}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")


def test_parent_profile_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/parent-profile/")
    assert response.status_code == 401


def test_parent_profile_get_includes_children_and_update_location(api_client):
    _login_parent(
        api_client,
        "parent.profile@example.ci",
        children=[{"first_name": "Aïcha", "class_level": "5ème", "target_subjects": ["Anglais"]}],
    )

    get_response = api_client.get("/api/v1/auth/parent-profile/")
    assert get_response.status_code == 200
    assert get_response.data["location"] == "Marcory, Abidjan"
    assert len(get_response.data["children"]) == 1
    assert get_response.data["children"][0]["first_name"] == "Aïcha"
    assert get_response.data["subscription_active"] is False

    patch_response = api_client.patch(
        "/api/v1/auth/parent-profile/", {"location": "Cocody, Abidjan"}, format="json"
    )
    assert patch_response.status_code == 200
    assert patch_response.data["location"] == "Cocody, Abidjan"


def test_parent_profile_forbidden_for_other_roles(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "notparent@example.ci", "password": "testpass123", "first_name": "N", "last_name": "P"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "notparent@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/auth/parent-profile/")
    assert response.status_code == 403


def test_children_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/children/")
    assert response.status_code == 401


def test_children_add_list_update_delete(api_client):
    _login_parent(api_client, "parent.children@example.ci")

    create_response = api_client.post(
        "/api/v1/auth/children/",
        {"first_name": "Ibrahim", "class_level": "CM2", "target_subjects": ["Français"]},
        format="json",
    )
    assert create_response.status_code == 201
    child_id = create_response.data["id"]

    list_response = api_client.get("/api/v1/auth/children/")
    assert list_response.status_code == 200
    assert len(list_response.data) == 1

    update_response = api_client.patch(
        f"/api/v1/auth/children/{child_id}/", {"class_level": "6ème"}, format="json"
    )
    assert update_response.status_code == 200
    assert update_response.data["class_level"] == "6ème"

    delete_response = api_client.delete(f"/api/v1/auth/children/{child_id}/")
    assert delete_response.status_code == 204

    list_after_delete = api_client.get("/api/v1/auth/children/")
    assert len(list_after_delete.data) == 0


def test_children_max_five_enforced_on_add_endpoint(api_client):
    _login_parent(
        api_client,
        "parent.maxchildren@example.ci",
        children=[
            {"first_name": f"Enfant{i}", "class_level": "CM2", "target_subjects": []}
            for i in range(5)
        ],
    )
    response = api_client.post(
        "/api/v1/auth/children/",
        {"first_name": "Sixième", "class_level": "CM1", "target_subjects": []},
        format="json",
    )
    assert response.status_code == 400


def test_children_isolated_between_parents(api_client):
    _login_parent(
        api_client,
        "parent.a@example.ci",
        children=[{"first_name": "EnfantA", "class_level": "CM2", "target_subjects": []}],
    )
    child_id = api_client.get("/api/v1/auth/children/").data[0]["id"]

    api_client.credentials()
    _login_parent(api_client, "parent.b@example.ci")

    response = api_client.get(f"/api/v1/auth/children/{child_id}/")
    assert response.status_code == 404


def _login_teacher(api_client, email):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": email, "password": "testpass123", "first_name": "K", "last_name": "Y"},
        format="json",
    )
    login = api_client.post("/api/v1/auth/token/", {"email": email, "password": "testpass123"}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")


def test_change_password_requires_authentication(api_client):
    response = api_client.post("/api/v1/auth/me/change-password/", {}, format="json")
    assert response.status_code == 401


def test_change_password_wrong_old_password_rejected(api_client):
    _login_teacher(api_client, "pwd.wrong@example.ci")
    response = api_client.post(
        "/api/v1/auth/me/change-password/",
        {"old_password": "nope", "new_password": "newpass123"},
        format="json",
    )
    assert response.status_code == 400


def test_change_password_succeeds_and_new_password_works(api_client):
    _login_teacher(api_client, "pwd.ok@example.ci")
    response = api_client.post(
        "/api/v1/auth/me/change-password/",
        {"old_password": "testpass123", "new_password": "newpass456"},
        format="json",
    )
    assert response.status_code == 200

    fresh_client = APIClient()
    login = fresh_client.post(
        "/api/v1/auth/token/", {"email": "pwd.ok@example.ci", "password": "newpass456"}, format="json"
    )
    assert login.status_code == 200


def test_my_data_export_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/me/export/")
    assert response.status_code == 401


def test_my_data_export_includes_account_and_role_profile(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {
            "email": "export.teacher@example.ci", "password": "testpass123",
            "first_name": "E", "last_name": "T", "subjects": ["Maths"],
        },
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "export.teacher@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = api_client.get("/api/v1/auth/me/export/")
    assert response.status_code == 200
    assert response.data["account"]["email"] == "export.teacher@example.ci"
    assert response.data["profiles"]["teacher"]["subjects"] == ["Maths"]


def test_request_deletion_requires_correct_password(api_client):
    _login_teacher(api_client, "del.wrongpwd@example.ci")
    response = api_client.post(
        "/api/v1/auth/me/request-deletion/", {"password": "wrong"}, format="json"
    )
    assert response.status_code == 400
    assert User.objects.get(email="del.wrongpwd@example.ci").is_active is True


def test_request_deletion_anonymizes_and_deactivates_account(api_client):
    _login_teacher(api_client, "del.ok@example.ci")
    user_id = User.objects.get(email="del.ok@example.ci").id

    response = api_client.post(
        "/api/v1/auth/me/request-deletion/", {"password": "testpass123"}, format="json"
    )
    assert response.status_code == 200

    user = User.objects.get(id=user_id)
    assert user.is_active is False
    assert user.email == f"compte-supprime-{user.id}@xporadia.invalid"
    assert user.first_name == "Compte"
    assert user.deletion_requested_at is not None
    assert user.has_usable_password() is False


def test_deactivated_account_cannot_login_again(api_client):
    _login_teacher(api_client, "del.relogin@example.ci")
    api_client.post("/api/v1/auth/me/request-deletion/", {"password": "testpass123"}, format="json")

    fresh_client = APIClient()
    response = fresh_client.post(
        "/api/v1/auth/token/", {"email": "del.relogin@example.ci", "password": "testpass123"}, format="json"
    )
    assert response.status_code == 401


def _create_teacher(email, subjects=None, visible=True, active=True, **profile_kwargs):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="Prénom", last_name="Nom",
        primary_role=UserRole.TEACHER, is_active=active, profile_visible=visible,
    )
    TeacherProfile.objects.create(user=user, subjects=subjects or [], **profile_kwargs)
    return user


def test_teacher_directory_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/teachers/")
    assert response.status_code == 401


def test_teacher_directory_forbidden_for_non_teacher(api_client):
    api_client.post(
        "/api/v1/auth/register/parent/",
        {"email": "parent.directory@example.ci", "password": "testpass123", "first_name": "P", "last_name": "D"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "parent.directory@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = api_client.get("/api/v1/auth/teachers/")
    assert response.status_code == 403


def test_teacher_directory_excludes_self_hidden_and_inactive(api_client):
    _login_teacher(api_client, "viewer@example.ci")
    visible = _create_teacher("visible.colleague@example.ci", subjects=["Maths"])
    _create_teacher("hidden.colleague@example.ci", subjects=["Maths"], visible=False)
    _create_teacher("inactive.colleague@example.ci", subjects=["Maths"], active=False)

    response = api_client.get("/api/v1/auth/teachers/")
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["id"] == visible.id


def test_teacher_directory_hides_hourly_rate_and_contact_info(api_client):
    _login_teacher(api_client, "viewer2@example.ci")
    _create_teacher("colleague2@example.ci", subjects=["Maths"], hourly_rate="7000")

    response = api_client.get("/api/v1/auth/teachers/")
    assert response.status_code == 200
    results = response.data["results"]
    assert "hourly_rate" not in results[0]
    assert "email" not in results[0]
    assert "phone" not in results[0]


def test_teacher_directory_filter_by_subject(api_client):
    _login_teacher(api_client, "viewer3@example.ci")
    _create_teacher("math.teacher@example.ci", subjects=["Mathématiques"])
    _create_teacher("french.teacher@example.ci", subjects=["Français"])

    response = api_client.get("/api/v1/auth/teachers/?subject=math")
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["subjects"] == ["Mathématiques"]


def test_teacher_directory_detail_includes_bio_and_certifications(api_client):
    _login_teacher(api_client, "viewer4@example.ci")
    colleague = _create_teacher("colleague4@example.ci", subjects=["SVT"], bio="Passionnée de sciences.")

    response = api_client.get(f"/api/v1/auth/teachers/{colleague.id}/")
    assert response.status_code == 200
    assert response.data["bio"] == "Passionnée de sciences."
    assert response.data["certifications"] == []
    assert response.data["current_level"] is None


def test_teacher_directory_detail_404_for_self(api_client):
    api_client.post(
        "/api/v1/auth/register/teacher/",
        {"email": "selfview@example.ci", "password": "testpass123", "first_name": "S", "last_name": "V"},
        format="json",
    )
    login = api_client.post(
        "/api/v1/auth/token/", {"email": "selfview@example.ci", "password": "testpass123"}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    self_id = User.objects.get(email="selfview@example.ci").id

    response = api_client.get(f"/api/v1/auth/teachers/{self_id}/")
    assert response.status_code == 404


def test_teacher_directory_detail_404_for_unknown_teacher(api_client):
    _login_teacher(api_client, "viewer5@example.ci")
    response = api_client.get("/api/v1/auth/teachers/999999/")
    assert response.status_code == 404
