from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id", "amount", "currency", "operator", "status", "payment_type",
            "tx_ref", "created_at", "completed_at",
        ]
        read_only_fields = fields
