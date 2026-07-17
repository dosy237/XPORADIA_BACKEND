import pytest
from rest_framework.test import APIClient

from apps.academics.models import Department, Enrollment, SchoolClass, Subject, TeacherInvitation, Track
from apps.notifications.models import Notification
from apps.users.models import Child, DirectorProfile, ParentProfile, TeacherProfile, User, UserRole

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


def test_subject_teacher_email_without_teacher_account_creates_invitation(api_client):
    titulaire = _create_teacher(email="titulaire.noaccount@example.ci")
    _, school_class = _create_class(school_year="2020-2025", homeroom_teacher=titulaire)
    _login(api_client, titulaire.email)

    response = api_client.post(
        f"/api/v1/academics/classes/{school_class.id}/subjects/",
        {"name": "SVT", "teacher_email": "unknown.teacher@example.ci"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["teacher"] is None
    assert response.data["pending_invitation_email"] == "unknown.teacher@example.ci"
    assert response.data["pending_invitation_token"]
    invitation = TeacherInvitation.objects.get(subject__name="SVT")
    assert invitation.email == "unknown.teacher@example.ci"
    assert invitation.invited_by == titulaire
    assert not invitation.is_accepted


def test_subject_teacher_email_matching_non_teacher_account_creates_invitation(api_client):
    titulaire = _create_teacher(email="titulaire.wrongrole@example.ci")
    parent = User.objects.create_user(
        email="parent.subject@example.ci", password="testpass123", first_name="P", last_name="A",
        primary_role=UserRole.PARENT,
    )
    _, school_class = _create_class(school_year="2020-2029", homeroom_teacher=titulaire)
    _login(api_client, titulaire.email)

    response = api_client.post(
        f"/api/v1/academics/classes/{school_class.id}/subjects/",
        {"name": "SVT", "teacher_email": parent.email},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["teacher"] is None
    assert TeacherInvitation.objects.filter(email=parent.email).exists()


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


def _create_invitation(email="invited.teacher@example.ci", school_year="2020-2030"):
    titulaire = _create_teacher(email=f"titulaire.inv.{school_year}@example.ci")
    _, school_class = _create_class(school_year=school_year, homeroom_teacher=titulaire)
    subject = Subject.objects.create(school_class=school_class, name="Maths")
    invitation = TeacherInvitation.objects.create(subject=subject, email=email, invited_by=titulaire)
    return titulaire, subject, invitation


def test_teacher_invitation_preview_is_public(api_client):
    _, subject, invitation = _create_invitation(school_year="2020-2030")
    response = api_client.get(f"/api/v1/academics/invitations/{invitation.token}/")
    assert response.status_code == 200
    assert response.data["subject_name"] == "Maths"
    assert response.data["email"] == "invited.teacher@example.ci"
    assert response.data["school_class_name"] == subject.school_class.name


def test_teacher_invitation_preview_404_for_unknown_token(api_client):
    response = api_client.get("/api/v1/academics/invitations/unknown-token/")
    assert response.status_code == 404


def test_accept_invitation_requires_authentication(api_client):
    _, _, invitation = _create_invitation(school_year="2020-2031")
    response = api_client.post(f"/api/v1/academics/invitations/{invitation.token}/accept/")
    assert response.status_code == 401


def test_accept_invitation_forbidden_for_wrong_email(api_client):
    _, _, invitation = _create_invitation(email="invited.correct@example.ci", school_year="2020-2032")
    wrong_teacher = _create_teacher(email="wrong.email@example.ci")
    _login(api_client, wrong_teacher.email)

    response = api_client.post(f"/api/v1/academics/invitations/{invitation.token}/accept/")
    assert response.status_code == 403


def test_accept_invitation_forbidden_for_non_teacher(api_client):
    _, _, invitation = _create_invitation(email="director.email@example.ci", school_year="2020-2033")
    director, _ = _create_director(email="director.email@example.ci")
    _login(api_client, director.email)

    response = api_client.post(f"/api/v1/academics/invitations/{invitation.token}/accept/")
    assert response.status_code == 403


def test_accept_invitation_assigns_teacher_and_notifies_inviter(api_client):
    titulaire, subject, invitation = _create_invitation(
        email="accepting.teacher@example.ci", school_year="2020-2034"
    )
    invited_teacher = _create_teacher(email="accepting.teacher@example.ci")
    _login(api_client, invited_teacher.email)

    response = api_client.post(f"/api/v1/academics/invitations/{invitation.token}/accept/")
    assert response.status_code == 200
    subject.refresh_from_db()
    assert subject.teacher == invited_teacher

    invitation.refresh_from_db()
    assert invitation.is_accepted is True
    assert invitation.accepted_by == invited_teacher
    assert invitation.accepted_at is not None
    assert Notification.objects.filter(user=titulaire, notif_type="class_assignment").exists()


def test_accept_invitation_already_accepted_returns_404(api_client):
    _, _, invitation = _create_invitation(email="already.accepted@example.ci", school_year="2020-2035")
    invited_teacher = _create_teacher(email="already.accepted@example.ci")
    _login(api_client, invited_teacher.email)

    first = api_client.post(f"/api/v1/academics/invitations/{invitation.token}/accept/")
    assert first.status_code == 200
    second = api_client.post(f"/api/v1/academics/invitations/{invitation.token}/accept/")
    assert second.status_code == 404


def _create_parent_with_child(email="parent@example.ci", child_name="Aïcha", class_level="Terminale"):
    user = User.objects.create_user(
        email=email, password="testpass123", first_name="P", last_name="A",
        primary_role=UserRole.PARENT,
    )
    profile = ParentProfile.objects.create(user=user, location="Cocody")
    child = Child.objects.create(parent=profile, first_name=child_name, class_level=class_level)
    return user, profile, child


def _create_second_class_same_establishment(profile, school_year="2025-2026", name="2nde C"):
    department = Department.objects.filter(establishment=profile).first()
    track = department.tracks.first()
    return SchoolClass.objects.create(track=track, name=name, school_year=school_year)


def test_children_lookup_requires_authentication(api_client):
    response = api_client.get("/api/v1/academics/children-lookup/", {"parent_email": "x@example.ci"})
    assert response.status_code == 401


def test_children_lookup_forbidden_for_parent(api_client):
    parent, _, _ = _create_parent_with_child(email="parent.forbidden@example.ci")
    _login(api_client, parent.email)

    response = api_client.get("/api/v1/academics/children-lookup/", {"parent_email": parent.email})
    assert response.status_code == 403


def test_children_lookup_returns_parents_children(api_client):
    titulaire = _create_teacher(email="titulaire.lookup@example.ci")
    parent, _, child = _create_parent_with_child(email="parent.lookup@example.ci", child_name="Kader")
    _login(api_client, titulaire.email)

    response = api_client.get("/api/v1/academics/children-lookup/", {"parent_email": parent.email})
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["first_name"] == "Kader"


def test_children_lookup_empty_for_unknown_parent(api_client):
    titulaire = _create_teacher(email="titulaire.lookupunknown@example.ci")
    _login(api_client, titulaire.email)

    response = api_client.get("/api/v1/academics/children-lookup/", {"parent_email": "nobody@example.ci"})
    assert response.status_code == 200
    assert response.data == []


def test_roster_requires_authentication(api_client):
    titulaire = _create_teacher(email="titulaire.rosterauth@example.ci")
    _, school_class = _create_class(school_year="2021-2021", homeroom_teacher=titulaire)
    response = api_client.get(f"/api/v1/academics/classes/{school_class.id}/roster/")
    assert response.status_code == 401


def test_roster_forbidden_for_unrelated_teacher(api_client):
    titulaire = _create_teacher(email="titulaire.rosterother@example.ci")
    other = _create_teacher(email="other.rosterother@example.ci")
    _, school_class = _create_class(school_year="2021-2022", homeroom_teacher=titulaire)

    _login(api_client, other.email)
    response = api_client.get(f"/api/v1/academics/classes/{school_class.id}/roster/")
    assert response.status_code == 403


def test_director_can_view_roster_of_own_establishment_class(api_client):
    titulaire = _create_teacher(email="titulaire.rosterdirector@example.ci")
    director, school_class = _create_class(school_year="2021-2023", homeroom_teacher=titulaire)

    _login(api_client, director.email)
    response = api_client.get(f"/api/v1/academics/classes/{school_class.id}/roster/")
    assert response.status_code == 200


def test_homeroom_teacher_enrolls_child_and_notifies_parent(api_client):
    titulaire = _create_teacher(email="titulaire.enroll@example.ci")
    _, school_class = _create_class(school_year="2021-2024", homeroom_teacher=titulaire)
    parent, _, child = _create_parent_with_child(email="parent.enroll@example.ci", child_name="Fatou")
    _login(api_client, titulaire.email)

    response = api_client.post(
        f"/api/v1/academics/classes/{school_class.id}/roster/", {"child_id": child.id}, format="json"
    )
    assert response.status_code == 201
    assert Enrollment.objects.filter(child=child, school_class=school_class, status="active").exists()
    assert response.data["child"]["first_name"] == "Fatou"
    assert Notification.objects.filter(user=parent, notif_type="enrollment_update").exists()


def test_enroll_missing_child_id_returns_400(api_client):
    titulaire = _create_teacher(email="titulaire.enrollmissing@example.ci")
    _, school_class = _create_class(school_year="2021-2025", homeroom_teacher=titulaire)
    _login(api_client, titulaire.email)

    response = api_client.post(f"/api/v1/academics/classes/{school_class.id}/roster/", {}, format="json")
    assert response.status_code == 400


def test_roster_lists_only_active_enrollments(api_client):
    titulaire = _create_teacher(email="titulaire.rosterlist@example.ci")
    _, school_class = _create_class(school_year="2021-2026", homeroom_teacher=titulaire)
    _, _, active_child = _create_parent_with_child(email="parent.active@example.ci", child_name="Actif")
    _, _, withdrawn_child = _create_parent_with_child(email="parent.withdrawn@example.ci", child_name="Parti")
    Enrollment.objects.create(child=active_child, school_class=school_class, status="active")
    Enrollment.objects.create(child=withdrawn_child, school_class=school_class, status="withdrawn")

    _login(api_client, titulaire.email)
    response = api_client.get(f"/api/v1/academics/classes/{school_class.id}/roster/")
    assert response.status_code == 200
    names = [e["child"]["first_name"] for e in response.data]
    assert names == ["Actif"]


def test_transition_requires_director(api_client):
    titulaire = _create_teacher(email="titulaire.transitionauth@example.ci")
    _, school_class = _create_class(school_year="2021-2027", homeroom_teacher=titulaire)
    _, _, child = _create_parent_with_child(email="parent.transitionauth@example.ci")
    enrollment = Enrollment.objects.create(child=child, school_class=school_class, status="active")

    _login(api_client, titulaire.email)
    response = api_client.post(
        f"/api/v1/academics/roster/{enrollment.id}/transition/", {"status": "withdrawn"}, format="json"
    )
    assert response.status_code == 403


def test_director_withdraws_child_and_notifies_parent(api_client):
    titulaire = _create_teacher(email="titulaire.withdraw@example.ci")
    director, school_class = _create_class(school_year="2021-2028", homeroom_teacher=titulaire)
    parent, _, child = _create_parent_with_child(email="parent.withdraw@example.ci", child_name="Yao")
    enrollment = Enrollment.objects.create(child=child, school_class=school_class, status="active")

    _login(api_client, director.email)
    response = api_client.post(
        f"/api/v1/academics/roster/{enrollment.id}/transition/", {"status": "withdrawn"}, format="json"
    )
    assert response.status_code == 200
    enrollment.refresh_from_db()
    assert enrollment.status == "withdrawn"
    assert enrollment.ended_at is not None
    assert response.data["new_enrollment"] is None
    assert Notification.objects.filter(user=parent, notif_type="enrollment_update").exists()


def test_director_promotes_child_to_target_class_in_same_establishment(api_client):
    titulaire = _create_teacher(email="titulaire.promote@example.ci")
    director, school_class = _create_class(school_year="2021-2029", homeroom_teacher=titulaire)
    profile = director.director_profile
    target_class = _create_second_class_same_establishment(profile, school_year="2022-2030")
    _, _, child = _create_parent_with_child(email="parent.promote@example.ci", child_name="Awa")
    enrollment = Enrollment.objects.create(child=child, school_class=school_class, status="active")

    _login(api_client, director.email)
    response = api_client.post(
        f"/api/v1/academics/roster/{enrollment.id}/transition/",
        {"status": "promoted", "target_class_id": target_class.id},
        format="json",
    )
    assert response.status_code == 200
    enrollment.refresh_from_db()
    assert enrollment.status == "promoted"
    assert response.data["new_enrollment"]["school_class"]["id"] == target_class.id
    assert Enrollment.objects.filter(child=child, school_class=target_class, status="active").exists()


def test_promotion_requires_target_class_id(api_client):
    titulaire = _create_teacher(email="titulaire.promotemissing@example.ci")
    director, school_class = _create_class(school_year="2021-2031", homeroom_teacher=titulaire)
    _, _, child = _create_parent_with_child(email="parent.promotemissing@example.ci")
    enrollment = Enrollment.objects.create(child=child, school_class=school_class, status="active")

    _login(api_client, director.email)
    response = api_client.post(
        f"/api/v1/academics/roster/{enrollment.id}/transition/", {"status": "promoted"}, format="json"
    )
    assert response.status_code == 400


def test_director_cannot_promote_to_class_outside_own_establishment(api_client):
    titulaire = _create_teacher(email="titulaire.promoteforeign@example.ci")
    director, school_class = _create_class(school_year="2021-2032", homeroom_teacher=titulaire)
    _, foreign_class = _create_class(school_year="2021-2033")
    _, _, child = _create_parent_with_child(email="parent.promoteforeign@example.ci")
    enrollment = Enrollment.objects.create(child=child, school_class=school_class, status="active")

    _login(api_client, director.email)
    response = api_client.post(
        f"/api/v1/academics/roster/{enrollment.id}/transition/",
        {"status": "promoted", "target_class_id": foreign_class.id},
        format="json",
    )
    assert response.status_code == 403
