import uuid

from django.core.exceptions import ValidationError
from django.db import models


class Merchant(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class BankAccount(models.Model):
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="bank_accounts")
    label = models.CharField(max_length=80)
    account_number = models.CharField(max_length=32)
    ifsc = models.CharField(max_length=16)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.account_number[-4:]})"


class LedgerEntry(models.Model):
    CREDIT = "credit"
    HOLD = "hold"
    HOLD_RELEASE = "hold_release"
    DEBIT = "debit"
    ENTRY_TYPES = (
        (CREDIT, "Credit"),
        (HOLD, "Hold"),
        (HOLD_RELEASE, "Hold Release"),
        (DEBIT, "Debit"),
    )

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="ledger_entries")
    payout = models.ForeignKey("Payout", on_delete=models.SET_NULL, null=True, blank=True, related_name="ledger_entries")
    entry_type = models.CharField(max_length=24, choices=ENTRY_TYPES)
    amount_paise = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Payout(models.Model):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STATUSES = (
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="payouts")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="payouts")
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=24, choices=STATUSES, default=PENDING)
    failure_reason = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.UUIDField()
    idempotency_expires_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["merchant", "idempotency_key"]),
        ]

    def clean(self):
        if self.amount_paise <= 0:
            raise ValidationError("Payout amount must be positive.")

    def transition(self, to_status: str):
        legal = {
            self.PENDING: {self.PROCESSING},
            self.PROCESSING: {self.COMPLETED, self.FAILED},
            self.COMPLETED: set(),
            self.FAILED: set(),
        }
        if to_status not in legal[self.status]:
            raise ValidationError(f"Illegal status transition from {self.status} to {to_status}")
        self.status = to_status


class IdempotencyRecord(models.Model):
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="idempotency_records")
    key = models.UUIDField()
    payout = models.ForeignKey(Payout, on_delete=models.SET_NULL, null=True, blank=True, related_name="idempotency_records")
    response_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "key"], name="uniq_idempotency_record_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "key"]),
            models.Index(fields=["expires_at"]),
        ]
