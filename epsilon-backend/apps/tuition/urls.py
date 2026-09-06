from django.urls import path

from . import views

urlpatterns = [
    path("fee-schedule/", views.FeeScheduleView.as_view(), name="fee-schedule"),
    path(
        "fee-schedules/<int:schedule_id>/installments/",
        views.FeeInstallmentListCreateView.as_view(),
        name="fee-installment-list-create",
    ),
    path(
        "fee-installments/<int:pk>/",
        views.FeeInstallmentDetailView.as_view(),
        name="fee-installment-detail",
    ),
    path("children/<int:child_id>/fees/", views.ChildFeeStatusView.as_view(), name="child-fee-status"),
    path(
        "children/<int:child_id>/fees/installments/<int:installment_id>/payments/",
        views.RecordFeePaymentView.as_view(),
        name="record-fee-payment",
    ),
    path(
        "children/<int:child_id>/fees/remind/",
        views.RemindLateFamilyView.as_view(),
        name="remind-late-family",
    ),
    path("fee-dashboard/", views.EstablishmentFeeDashboardView.as_view(), name="fee-dashboard"),
]
