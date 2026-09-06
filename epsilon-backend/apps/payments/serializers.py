from rest_framework import serializers

from .models import Dispute, Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id", "amount", "currency", "method", "operator", "card_last4", "status", "payment_type",
            "tx_ref", "created_at", "completed_at",
        ]
        read_only_fields = fields


class DisputeSerializer(serializers.ModelSerializer):
    payment_amount = serializers.IntegerField(source="payment.amount", read_only=True)
    payment_type = serializers.CharField(source="payment.get_payment_type_display", read_only=True)
    opened_by_name = serializers.CharField(source="opened_by.get_full_name", read_only=True)

    class Meta:
        model = Dispute
        fields = [
            "id", "payment", "payment_amount", "payment_type", "opened_by", "opened_by_name",
            "reason", "status", "resolution", "resolved_at", "created_at",
        ]
        read_only_fields = [
            "id", "payment_amount", "payment_type", "opened_by", "opened_by_name",
            "status", "resolution", "resolved_at", "created_at",
        ]
