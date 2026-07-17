from django.urls import path

from . import views

urlpatterns = [
    path("my-payments/", views.MyPaymentsView.as_view(), name="my-payments"),
]
