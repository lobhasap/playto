from django.db.models import BigIntegerField, Case, F, Sum, Value, When
from rest_framework import serializers

from .models import LedgerEntry, Payout


class PayoutCreateSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.IntegerField(min_value=1)


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = [
            "id",
            "merchant",
            "bank_account",
            "amount_paise",
            "status",
            "failure_reason",
            "attempts",
            "created_at",
            "updated_at",
        ]


class MerchantDashboardSerializer(serializers.Serializer):
    merchant_id = serializers.IntegerField()
    available_balance_paise = serializers.IntegerField()
    held_balance_paise = serializers.IntegerField()
    recent_ledger = serializers.ListField()
    payouts = serializers.ListField()


def ledger_sums_for_merchant(merchant):
    signed_amount = Case(
        When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
        When(entry_type=LedgerEntry.HOLD_RELEASE, then=F("amount_paise")),
        default=Value(0) - F("amount_paise"),
        output_field=BigIntegerField(),
    )
    held_amount = Case(
        When(entry_type=LedgerEntry.HOLD, then=F("amount_paise")),
        When(entry_type=LedgerEntry.HOLD_RELEASE, then=Value(0) - F("amount_paise")),
        default=Value(0),
        output_field=BigIntegerField(),
    )
    totals = merchant.ledger_entries.aggregate(
        available_balance_paise=Sum(signed_amount),
        held_balance_paise=Sum(held_amount),
    )
    return {
        "available_balance_paise": totals["available_balance_paise"] or 0,
        "held_balance_paise": totals["held_balance_paise"] or 0,
    }
