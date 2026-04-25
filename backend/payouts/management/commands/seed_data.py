from django.core.management.base import BaseCommand

from payouts.models import BankAccount, LedgerEntry, Merchant


class Command(BaseCommand):
    help = "Seed merchants and historical credits."

    def handle(self, *args, **kwargs):
        merchants = [
            ("Alpha Stores", "alpha@example.com"),
            ("Beta Bazaar", "beta@example.com"),
            ("Gamma Goods", "gamma@example.com"),
        ]
        for idx, (name, email) in enumerate(merchants, start=1):
            merchant, _ = Merchant.objects.get_or_create(name=name, email=email)
            BankAccount.objects.get_or_create(
                merchant=merchant,
                account_number=f"900000000{idx:03}",
                defaults={
                    "label": "Primary",
                    "ifsc": f"PLAY0000{idx:03}",
                },
            )
            for amount in [50_000, 25_000, 10_000]:
                LedgerEntry.objects.get_or_create(
                    merchant=merchant,
                    entry_type=LedgerEntry.CREDIT,
                    amount_paise=amount,
                )

        self.stdout.write(self.style.SUCCESS("Seeded merchants, bank accounts, and credit history."))
