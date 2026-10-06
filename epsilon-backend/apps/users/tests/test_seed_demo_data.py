from django.core.management import call_command

import pytest

from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_seed_demo_data_runs_and_creates_accounts():
    call_command("seed_demo_data")
    assert User.objects.filter(email__endswith="@xporadia.ci").count() >= 13


def test_seed_demo_data_rebuilds_consistently_when_run_twice():
    call_command("seed_demo_data")
    count_after_first_run = User.objects.count()
    call_command("seed_demo_data")
    assert User.objects.count() == count_after_first_run


def test_seed_demo_data_wipes_all_existing_users_not_just_demo_accounts():
    real_user = User.objects.create_user(
        email="real.person@example.com", password="whatever", first_name="Real", last_name="Person"
    )
    call_command("seed_demo_data")
    assert not User.objects.filter(pk=real_user.pk).exists()
