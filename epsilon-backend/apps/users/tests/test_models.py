import pytest
from django.utils import timezone
from datetime import timedelta

from apps.users.models import (
    Child,
    DirectorProfile,
    OTPCode,
    OTPPurpose,
    ParentProfile,
    TeacherProfile,
    User,
    UserRole,
)

pytestmark = pytest.mark.django_db


def test_create_user_hashes_password():
    user = User.objects.create_user(
        email="Kouame@Example.CI",
        password="testpass123",
        first_name="Kouame",
        last_name="Yao",
        primary_role=UserRole.TEACHER,
    )
    assert user.email == "Kouame@example.ci"
    assert user.check_password("testpass123")
    assert user.password != "testpass123"


def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x", first_name="A", last_name="B")


def test_create_superuser_sets_admin_role():
    admin = User.objects.create_superuser(
        email="admin@xporadia.ci", password="adminpass123",
        first_name="Admin", last_name="Xporadia",
    )
    assert admin.is_staff
    assert admin.is_superuser
    assert admin.primary_role == UserRole.ADMIN


def test_get_all_roles_and_has_role():
    user = User.objects.create_user(
        email="multi@example.ci", password="testpass123",
        first_name="Multi", last_name="Role",
        primary_role=UserRole.TEACHER, secondary_roles=[UserRole.PARENT],
    )
    assert set(user.get_all_roles()) == {UserRole.TEACHER, UserRole.PARENT}
    assert user.has_role(UserRole.PARENT)
    assert not user.has_role(UserRole.DIRECTOR)


def test_teacher_profile_one_to_one():
    user = User.objects.create_user(
        email="teacher@example.ci", password="testpass123",
        first_name="T", last_name="P", primary_role=UserRole.TEACHER,
    )
    profile = TeacherProfile.objects.create(user=user, subjects=["Maths"], experience_years=3)
    assert user.teacher_profile == profile
    assert profile.subjects == ["Maths"]


def test_director_profile():
    user = User.objects.create_user(
        email="director@example.ci", password="testpass123",
        first_name="D", last_name="P", primary_role=UserRole.DIRECTOR,
    )
    profile = DirectorProfile.objects.create(
        user=user, school_name="Lycee Test", address="Abidjan"
    )
    assert profile.is_partner is False
    assert user.director_profile.school_name == "Lycee Test"


def test_parent_profile_with_children():
    user = User.objects.create_user(
        email="parent@example.ci", password="testpass123",
        first_name="P", last_name="P", primary_role=UserRole.PARENT,
    )
    parent_profile = ParentProfile.objects.create(user=user, location="Marcory")
    Child.objects.create(parent=parent_profile, first_name="Awa", class_level="3eme")
    Child.objects.create(parent=parent_profile, first_name="Kofi", class_level="6eme")
    assert parent_profile.children.count() == 2


def test_otp_code_is_valid_when_fresh_and_unused():
    user = User.objects.create_user(
        email="otp@example.ci", password="testpass123",
        first_name="O", last_name="T", primary_role=UserRole.TEACHER,
    )
    otp = OTPCode.objects.create(
        user=user, code="123456", purpose=OTPPurpose.ACCOUNT_VERIFICATION,
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    assert otp.is_valid()


def test_otp_code_invalid_when_expired():
    user = User.objects.create_user(
        email="otp2@example.ci", password="testpass123",
        first_name="O", last_name="T", primary_role=UserRole.TEACHER,
    )
    otp = OTPCode.objects.create(
        user=user, code="123456", purpose=OTPPurpose.ACCOUNT_VERIFICATION,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    assert not otp.is_valid()


def test_otp_code_invalid_when_used():
    user = User.objects.create_user(
        email="otp3@example.ci", password="testpass123",
        first_name="O", last_name="T", primary_role=UserRole.TEACHER,
    )
    otp = OTPCode.objects.create(
        user=user, code="123456", purpose=OTPPurpose.ACCOUNT_VERIFICATION,
        expires_at=timezone.now() + timedelta(minutes=15), used=True,
    )
    assert not otp.is_valid()
