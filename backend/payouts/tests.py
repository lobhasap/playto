import threading
import uuid
from collections import Counter

from django.db import OperationalError
from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from .models import BankAccount, LedgerEntry, Merchant, Payout


class PayoutEngineTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.merchant = Merchant.objects.create(name="Merchant A", email="a@example.com")
        self.bank = BankAccount.objects.create(
            merchant=self.merchant,
            label="Primary",
            account_number="123456789012",
            ifsc="PLAY0000123",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.CREDIT,
            amount_paise=10_000,
        )

    def test_idempotency_returns_same_payout(self):
        client = APIClient()
        idem_key = str(uuid.uuid4())
        payload = {
            "merchant_id": self.merchant.id,
            "amount_paise": 2_000,
            "bank_account_id": self.bank.id,
        }
        first = client.post("/api/v1/payouts", payload, format="json", HTTP_IDEMPOTENCY_KEY=idem_key)
        second = client.post("/api/v1/payouts", payload, format="json", HTTP_IDEMPOTENCY_KEY=idem_key)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Payout.objects.count(), 1)
        self.assertEqual(
            LedgerEntry.objects.filter(entry_type=LedgerEntry.HOLD).count(),
            1,
        )

    def test_concurrent_payout_only_one_succeeds(self):
        results = []

        def fire_request():
            client = APIClient()
            try:
                response = client.post(
                    "/api/v1/payouts",
                    {
                        "merchant_id": self.merchant.id,
                        "amount_paise": 6_000,
                        "bank_account_id": self.bank.id,
                    },
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
                results.append(response.status_code)
            except OperationalError:
                # SQLite doesn't support fine-grained row-level locking and can throw table-lock errors.
                results.append(400)

        t1 = threading.Thread(target=fire_request)
        t2 = threading.Thread(target=fire_request)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(Payout.objects.count(), 1)
        if connection.vendor == "postgresql":
            counts = Counter(results)
            self.assertEqual(counts[201], 1)
            self.assertEqual(counts[400], 1)
        else:
            # SQLite lacks row-level locks; still verify no double-payout ever gets created.
            self.assertGreaterEqual(results.count(400), 1)
