from django.contrib import admin

from .models import FeeInstallment, FeePayment, FeeSchedule


@admin.register(FeeSchedule)
class FeeScheduleAdmin(admin.ModelAdmin):
    list_display = ["establishment", "school_year", "created_at"]
    list_filter = ["school_year"]


@admin.register(FeeInstallment)
class FeeInstallmentAdmin(admin.ModelAdmin):
    list_display = ["name", "fee_schedule", "amount", "due_date"]


@admin.register(FeePayment)
class FeePaymentAdmin(admin.ModelAdmin):
    list_display = ["child", "fee_installment", "amount_paid", "payment_channel", "paid_at"]
