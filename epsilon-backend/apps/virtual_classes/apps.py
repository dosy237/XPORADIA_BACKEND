from django.apps import AppConfig


class VirtualClassesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.virtual_classes"
    verbose_name = "virtual_classes"

    def ready(self):
        from . import signals  # noqa: F401
