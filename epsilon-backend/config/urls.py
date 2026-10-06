"""
Xporadia — URLs principales
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.static import serve as serve_static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Admin Django
    path("django-admin/", admin.site.urls),

    # Documentation API
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # Apps
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/academics/", include("apps.academics.urls")),
    path("api/v1/certification/", include("apps.certification.urls")),
    path("api/v1/employment/", include("apps.employment.urls")),
    path("api/v1/internships/", include("apps.internships.urls")),
    path("api/v1/virtual-classes/", include("apps.virtual_classes.urls")),
    path("api/v1/library/", include("apps.library.urls")),
    path("api/v1/payments/", include("apps.payments.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/feed/", include("apps.feed.urls")),
    path("api/v1/messaging/", include("apps.messaging.urls")),
    path("api/v1/grading/", include("apps.grading.urls")),
    path("api/v1/admin-panel/", include("apps.admin_panel.urls")),
    path("api/v1/student-life/", include("apps.student_life.urls")),
    path("api/v1/tuition/", include("apps.tuition.urls")),
    path("api/v1/documents/", include("apps.documents.urls")),
    path("api/v1/discipline/", include("apps.discipline.urls")),
]

# En production sans S3, Django sert les médias lui-même.
# On exempte de X-Frame-Options chaque dossier de PDFs affiché dans
# la visionneuse pour le web (iframe) et le WebView natif.
for pdf_subdir in ("library_pdfs", "report_cards"):
    urlpatterns += [
        re_path(
            rf"^media/{pdf_subdir}/(?P<path>.*)$",
            xframe_options_exempt(serve_static),
            {"document_root": settings.MEDIA_ROOT / pdf_subdir},
        ),
    ]

# Servir le reste des fichiers media statiquement (remplace static() qui ne marche qu'en DEBUG)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve_static, {'document_root': settings.MEDIA_ROOT}),
]
