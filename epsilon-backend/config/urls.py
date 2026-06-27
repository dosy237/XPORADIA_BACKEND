"""
Xporadia — URLs principales
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Admin Django
    path("django-admin/", admin.site.urls),

    # Documentation API
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # Apps
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/certification/", include("apps.certification.urls")),
    path("api/v1/employment/", include("apps.employment.urls")),
    path("api/v1/internships/", include("apps.internships.urls")),
    path("api/v1/tutoring/", include("apps.tutoring.urls")),
    path("api/v1/virtual-classes/", include("apps.virtual_classes.urls")),
    path("api/v1/library/", include("apps.library.urls")),
    path("api/v1/payments/", include("apps.payments.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
