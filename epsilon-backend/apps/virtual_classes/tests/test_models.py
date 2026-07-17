import pytest

from apps.academics.models import Department, SchoolClass, Subject, Track
from apps.users.models import DirectorProfile, TeacherProfile, User, UserRole
from apps.virtual_classes.models import VirtualClass

pytestmark = pytest.mark.django_db


def test_virtual_class_teacher_property_follows_subject_dedicated_teacher():
    teacher = User.objects.create_user(
        email="model.teacher@example.ci", password="testpass123", first_name="T", last_name="E",
        primary_role=UserRole.TEACHER,
    )
    TeacherProfile.objects.create(user=teacher)

    director_user = User.objects.create_user(
        email="model.dir@example.ci", password="testpass123", first_name="D", last_name="R",
        primary_role=UserRole.DIRECTOR,
    )
    profile = DirectorProfile.objects.create(user=director_user, school_name="École Test", address="Cocody")
    department = Department.objects.create(establishment=profile, name="Secondaire")
    track = Track.objects.create(department=department, name="Scientifique")
    school_class = SchoolClass.objects.create(track=track, name="Terminale D1", school_year="2040-2041")
    subject = Subject.objects.create(school_class=school_class, name="Maths", teacher=teacher)

    virtual_class = VirtualClass.objects.get(subject=subject)
    assert virtual_class.teacher == teacher
    assert str(virtual_class) == f"Espace numérique — {subject}"
