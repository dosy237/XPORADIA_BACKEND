"""
Xporadia — Settings staging
Usage : DJANGO_SETTINGS_MODULE=config.settings.staging
"""
from .base import *
import sentry_sdk

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["staging.xporadia.ci"])

# PostgreSQL
DATABASES = {
    "default": env.db("DATABASE_URL")
}

# Sentry — erreurs uniquement (pas perf en staging)
sentry_sdk.init(
    dsn=env("SENTRY_DSN", default=""),
    environment="staging",
    traces_sample_rate=0.1,
)

# Email — relais SMTP générique (voir prod.py pour le détail).
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="apikey")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default=env("SENDGRID_API_KEY", default=""))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@xporadia.ci")

# Storage S3
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_BUCKET_NAME", default="xporadia-staging")
AWS_S3_REGION_NAME = "eu-west-3"
