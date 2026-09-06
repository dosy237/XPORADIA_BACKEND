from django.apps import AppConfig


class LibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.library"
    verbose_name = "library"

    def ready(self):
        from . import signals  # noqa: F401
