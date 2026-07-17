from django.contrib import admin

from .models import Dispute, Payment, Reversal


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["tx_ref", "user", "amount", "operator", "payment_type", "status", "created_at"]
    list_filter = ["status", "payment_type", "operator"]
    search_fields = ["tx_ref", "user__email"]


@admin.register(Reversal)
class ReversalAdmin(admin.ModelAdmin):
    list_display = ["teacher", "payment", "amount", "operator", "status", "created_at"]
    list_filter = ["status", "operator"]


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ["payment", "opened_by", "status", "created_at"]
    list_filter = ["status"]
    actions = ["mark_resolved", "mark_closed"]

    @admin.action(description="Marquer comme résolu")
    def mark_resolved(self, request, queryset):
        from django.utils import timezone

        updated = queryset.update(status="resolved", resolved_by=request.user, resolved_at=timezone.now())
        self.message_user(request, f"{updated} litige(s) marqué(s) résolu(s).")

    @admin.action(description="Clôturer")
    def mark_closed(self, request, queryset):
        updated = queryset.update(status="closed")
        self.message_user(request, f"{updated} litige(s) clôturé(s).")
