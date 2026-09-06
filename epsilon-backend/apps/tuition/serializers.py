from rest_framework import serializers

from .models import FeeInstallment, FeePayment, FeeSchedule


class FeeInstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeInstallment
        fields = ["id", "name", "amount", "due_date"]
        read_only_fields = ["id"]


class FeeScheduleSerializer(serializers.ModelSerializer):
    installments = FeeInstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = FeeSchedule
        fields = ["id", "school_year", "installments", "created_at"]
        read_only_fields = fields


class FeePaymentSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source="recorded_by.get_full_name", read_only=True)

    class Meta:
        model = FeePayment
        fields = [
            "id", "child", "fee_installment", "amount_paid", "payment_channel",
            "paid_at", "recorded_by", "recorded_by_name",
        ]
        read_only_fields = ["id", "child", "recorded_by", "recorded_by_name", "paid_at"]


class InstallmentStatusSerializer(serializers.Serializer):
    installment = FeeInstallmentSerializer()
    amount_paid = serializers.IntegerField()
    amount_due = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["paid", "partial", "late", "pending"])
