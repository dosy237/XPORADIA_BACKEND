from django.urls import path

from . import views

urlpatterns = [
    path("my-payments/", views.MyPaymentsView.as_view(), name="my-payments"),
    path("payments/<uuid:payment_id>/dispute/", views.OpenDisputeView.as_view(), name="open-dispute"),
    path("admin/disputes/", views.AdminDisputesView.as_view(), name="admin-disputes"),
    path("admin/disputes/<int:pk>/resolve/", views.ResolveDisputeView.as_view(), name="resolve-dispute"),
]
