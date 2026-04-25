# EXPLAINER

## 1) The Ledger

Balance calculation query (used in `payouts/services.py`):

```python
merchant.ledger_entries.aggregate(
    balance=Coalesce(Sum(Case(
        When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
        When(entry_type=LedgerEntry.HOLD_RELEASE, then=F("amount_paise")),
        default=Value(0) - F("amount_paise"),
        output_field=BigIntegerField(),
    )), 0, output_field=BigIntegerField())
)["balance"]
```

Why this model:
- Ledger is append-only and immutable in practice (credits, holds, hold releases, debits).
- Balance is derived, not stored, so `credits - holds - debits + hold_releases` is auditable.
- Integer paise avoids float drift and rounding bugs.

## 2) The Lock

Exact lock code (in `create_payout_request`):

```python
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(id=merchant_id)
    ...
    balance_paise = get_available_balance_paise(merchant)
    if balance_paise < amount_paise:
        raise ValidationError("Insufficient available balance.")
    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(entry_type=LedgerEntry.HOLD, ...)
```

Primitive used:
- PostgreSQL row-level lock via `SELECT ... FOR UPDATE` on the merchant row.
- It serializes concurrent payout requests for the same merchant and prevents check-then-deduct races.

## 3) The Idempotency

How key lookup works:
- Header `Idempotency-Key` is parsed as UUID.
- Query: `IdempotencyRecord.objects.select_for_update().filter(merchant=merchant, key=idempotency_key).first()`.
- We store `response_status_code` and `response_body` in `IdempotencyRecord`.
- If the key exists and is not expired, we return the cached response body exactly as the first call saw it.
- Keys expire after 24 hours using `expires_at`; only the idempotency record is removed, never payout history.

If first request is in flight:
- First request holds merchant row lock in transaction.
- It also locks the idempotency record row and writes the cached first response during the initial request.
- Second request blocks on the same merchant/idempotency lock, then replays cached response after the first transaction commits.
- No duplicate payout row is created, and replay is byte-equivalent at the JSON payload level.

## 4) The State Machine

Blocked transition check in `Payout.transition`:

```python
legal = {
    self.PENDING: {self.PROCESSING},
    self.PROCESSING: {self.COMPLETED, self.FAILED},
    self.COMPLETED: set(),
    self.FAILED: set(),
}
if to_status not in legal[self.status]:
    raise ValidationError(f"Illegal status transition from {self.status} to {to_status}")
```

`failed -> completed` is blocked because `FAILED` allows no outgoing transitions.

## 5) The AI Audit

AI-suggested (wrong) code example:

```python
merchant = Merchant.objects.get(id=merchant_id)
if merchant.balance_paise >= amount_paise:
    merchant.balance_paise -= amount_paise
    merchant.save()
    Payout.objects.create(...)
```

What was wrong:
- Python-level read/modify/write with no lock.
- Two concurrent requests can both pass the balance check and overdraw.
- Also uses denormalized mutable balance that can drift from ledger.

What replaced it:
- Ledger-derived DB aggregation + `select_for_update` lock + atomic hold creation in one transaction.
- This guarantees only one conflicting payout can reserve funds.
