import uuid

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LedgerEntry, Merchant, Payout
from .serializers import MerchantDashboardSerializer, PayoutCreateSerializer, PayoutSerializer, ledger_sums_for_merchant
from .services import create_payout_request
from .tasks import process_single_payout


class PayoutCreateView(APIView):
    def post(self, request):
        merchant_id = request.data.get("merchant_id")
        if not merchant_id:
            return Response({"detail": "merchant_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        idem_header = request.headers.get("Idempotency-Key")
        if not idem_header:
            return Response({"detail": "Idempotency-Key header is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            idempotency_key = uuid.UUID(idem_header)
        except ValueError:
            return Response({"detail": "Idempotency-Key must be UUID."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PayoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        response_payload, response_status_code, created, payout_id = create_payout_request(
            merchant_id=merchant_id,
            amount_paise=serializer.validated_data["amount_paise"],
            bank_account_id=serializer.validated_data["bank_account_id"],
            idempotency_key=idempotency_key,
        )
        if created and payout_id:
            process_single_payout.delay(payout_id)
        return Response(response_payload, status=response_status_code)


class MerchantDashboardView(APIView):
    def get(self, request, merchant_id: int):
        merchant = get_object_or_404(Merchant, id=merchant_id)
        sums = ledger_sums_for_merchant(merchant)
        recent_ledger = list(
            merchant.ledger_entries.values("id", "entry_type", "amount_paise", "payout_id", "created_at")[:20]
        )
        payouts = list(
            merchant.payouts.values(
                "id",
                "amount_paise",
                "status",
                "failure_reason",
                "attempts",
                "created_at",
                "updated_at",
            )[:20]
        )
        payload = MerchantDashboardSerializer(
            {
                "merchant_id": merchant.id,
                "available_balance_paise": sums["available_balance_paise"],
                "held_balance_paise": sums["held_balance_paise"],
                "recent_ledger": recent_ledger,
                "payouts": payouts,
            }
        ).data
        return Response(payload)


class PayoutListView(APIView):
    def get(self, request, merchant_id: int):
        payouts = Payout.objects.filter(merchant_id=merchant_id)[:50]
        return Response(PayoutSerializer(payouts, many=True).data)


class MerchantListView(APIView):
    def get(self, request):
        merchants = list(Merchant.objects.values("id", "name", "email").order_by("id"))
        return Response(merchants)
