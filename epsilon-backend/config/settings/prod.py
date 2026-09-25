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
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
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

# Email — relais SMTP générique. Par défaut SendGrid (rétrocompatible avec
# SENDGRID_API_KEY), mais n'importe quel compte SMTP existant convient : une
# adresse Gmail avec un mot de passe d'application, une boîte pro déjà chez
# votre hébergeur, etc. — il suffit de renseigner EMAIL_HOST/EMAIL_HOST_USER/
# EMAIL_HOST_PASSWORD dans .env pour le remplacer, sans toucher au code.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="apikey")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default=env("SENDGRID_API_KEY", default=""))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@xporadia.ci")
SERVER_EMAIL = env("SERVER_EMAIL", default="ops@xporadia.ci")

# Storage S3 production
# DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
# AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
# AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
# AWS_STORAGE_BUCKET_NAME = env("AWS_BUCKET_NAME", default="xporadia-prod")
# AWS_S3_REGION_NAME = "eu-west-3"
# AWS_S3_CUSTOM_DOMAIN = env("AWS_CLOUDFRONT_DOMAIN", default="")
