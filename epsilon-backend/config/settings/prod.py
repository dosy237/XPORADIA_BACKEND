"""
Xporadia — Settings production
Usage : DJANGO_SETTINGS_MODULE=config.settings.prod
"""
from .base import *
import sentry_sdk

DEBUG = False

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["xporadia.ci", "www.xporadia.ci", "api.xporadia.ci"])

# Sécurité renforcée
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# PostgreSQL
DATABASES = {
    "default": env.db("DATABASE_URL"),
    "replica": env.db("DATABASE_REPLICA_URL", default=env("DATABASE_URL")),
}

# Sentry production
sentry_sdk.init(
    dsn=env("SENTRY_DSN"),
    environment="production",
    traces_sample_rate=0.05,
)

# Email
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.sendgrid.net"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "apikey"
EMAIL_HOST_PASSWORD = env("SENDGRID_API_KEY")
DEFAULT_FROM_EMAIL = "noreply@xporadia.ci"
SERVER_EMAIL = "ops@xporadia.ci"

# Storage S3 production
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = env("AWS_BUCKET_NAME", default="xporadia-prod")
AWS_S3_REGION_NAME = "eu-west-3"
AWS_S3_CUSTOM_DOMAIN = env("AWS_CLOUDFRONT_DOMAIN", default="")
