import pytest
from django.core.management import call_command

from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_seed_demo_data_runs_and_creates_accounts():
    call_command("seed_demo_data")
    assert User.objects.filter(email__endswith="@xporadia.ci").count() >= 13


def test_seed_demo_data_is_idempotent():
    call_command("seed_demo_data")
    count_after_first_run = User.objects.count()
    call_command("seed_demo_data")
    assert User.objects.count() == count_after_first_run


def test_seed_demo_data_reset_recreates_accounts_without_duplicating():
    call_command("seed_demo_data")
    count_after_first_run = User.objects.filter(email__endswith="@xporadia.ci").count()
    call_command("seed_demo_data", "--reset")
    assert User.objects.filter(email__endswith="@xporadia.ci").count() == count_after_first_run
