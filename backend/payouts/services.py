import random
from datetime import timedelta

from django.db import transaction
from django.db.models import BigIntegerField, Case, F, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import BankAccount, IdempotencyRecord, LedgerEntry, Merchant, Payout

MAX_RETRIES = 3


def _available_balance_expr():
    return Case(
        When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
        When(entry_type=LedgerEntry.HOLD_RELEASE, then=F("amount_paise")),
        default=Value(0) - F("amount_paise"),
        output_field=BigIntegerField(),
    )


def get_available_balance_paise(merchant: Merchant) -> int:
    return (
        merchant.ledger_entries.aggregate(
            balance=Coalesce(Sum(_available_balance_expr()), 0, output_field=BigIntegerField())
        )["balance"]
        or 0
    )


def _payout_response_payload(payout: Payout):
    return {
        "id": str(payout.id),
        "merchant": payout.merchant_id,
        "bank_account": payout.bank_account_id,
        "amount_paise": payout.amount_paise,
        "status": payout.status,
        "failure_reason": payout.failure_reason,
        "attempts": payout.attempts,
        "created_at": payout.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": payout.updated_at.isoformat().replace("+00:00", "Z"),
    }


def create_payout_request(merchant_id: int, amount_paise: int, bank_account_id: int, idempotency_key):
    now = timezone.now()
    with transaction.atomic():
        merchant = Merchant.objects.select_for_update().get(id=merchant_id)
        idempotency_record = (
            IdempotencyRecord.objects.select_for_update()
            .filter(merchant=merchant, key=idempotency_key)
            .first()
        )
        if idempotency_record:
            if idempotency_record.expires_at <= now:
                idempotency_record.delete()
                idempotency_record = None
            elif idempotency_record.response_body is not None and idempotency_record.response_status_code is not None:
                return idempotency_record.response_body, idempotency_record.response_status_code, False, None

        if idempotency_record is None:
            idempotency_record = IdempotencyRecord.objects.create(
                merchant=merchant,
                key=idempotency_key,
                expires_at=now + timedelta(hours=24),
            )

        account = BankAccount.objects.filter(id=bank_account_id, merchant=merchant, is_active=True).first()
        if not account:
            raise ValidationError("Invalid bank account for merchant.")

        balance_paise = get_available_balance_paise(merchant)
        if balance_paise < amount_paise:
            raise ValidationError("Insufficient available balance.")

        payout = Payout.objects.create(
            merchant=merchant,
            bank_account=account,
            amount_paise=amount_paise,
            status=Payout.PENDING,
            idempotency_key=idempotency_key,
            idempotency_expires_at=now + timedelta(hours=24),
        )
        LedgerEntry.objects.create(
            merchant=merchant,
            payout=payout,
            entry_type=LedgerEntry.HOLD,
            amount_paise=amount_paise,
        )
        payout.refresh_from_db()
        response_payload = _payout_response_payload(payout)
        idempotency_record.payout = payout
        idempotency_record.response_status_code = 201
        idempotency_record.response_body = response_payload
        idempotency_record.save(
            update_fields=["payout", "response_status_code", "response_body", "updated_at"]
        )
        return response_payload, 201, True, str(payout.id)


def process_payout(payout_id):
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("merchant").get(id=payout_id)
        if payout.status not in {Payout.PENDING, Payout.PROCESSING}:
            return payout.status
        if payout.status == Payout.PENDING:
            payout.transition(Payout.PROCESSING)
            payout.save(update_fields=["status", "updated_at"])

    # Simulated settlement outcome.
    draw = random.random()
    if draw < 0.7:
        return mark_payout_completed(payout_id)
    if draw < 0.9:
        return mark_payout_failed(payout_id, "bank_rejected")
    return schedule_retry(payout_id)


def mark_payout_completed(payout_id):
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("merchant").get(id=payout_id)
        if payout.status != Payout.PROCESSING:
            return payout.status
        payout.transition(Payout.COMPLETED)
        payout.save(update_fields=["status", "updated_at"])
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            payout=payout,
            entry_type=LedgerEntry.DEBIT,
            amount_paise=payout.amount_paise,
        )
        return payout.status


def mark_payout_failed(payout_id, reason: str):
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("merchant").get(id=payout_id)
        if payout.status != Payout.PROCESSING:
            return payout.status
        payout.transition(Payout.FAILED)
        payout.failure_reason = reason
        payout.save(update_fields=["status", "failure_reason", "updated_at"])
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            payout=payout,
            entry_type=LedgerEntry.HOLD_RELEASE,
            amount_paise=payout.amount_paise,
        )
        return payout.status


def schedule_retry(payout_id):
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)
        payout.attempts += 1
        if payout.attempts >= MAX_RETRIES:
            payout.next_retry_at = None
            payout.save(update_fields=["attempts", "next_retry_at", "updated_at"])
        else:
            payout.next_retry_at = timezone.now() + timedelta(seconds=2 ** payout.attempts)
            payout.save(update_fields=["attempts", "next_retry_at", "updated_at"])

    if payout.attempts >= MAX_RETRIES:
        return mark_payout_failed(payout_id, "max_retries_exceeded")
    return Payout.PROCESSING
