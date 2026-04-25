from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import Payout
from .services import process_payout


@shared_task
def enqueue_pending_payouts():
    ids = list(Payout.objects.filter(status=Payout.PENDING).values_list("id", flat=True))
    for payout_id in ids:
        process_single_payout.delay(str(payout_id))


@shared_task
def process_single_payout(payout_id: str):
    process_payout(payout_id)


@shared_task
def retry_stuck_payouts():
    cutoff = timezone.now() - timedelta(seconds=30)
    ids = list(
        Payout.objects.filter(
            status=Payout.PROCESSING,
            updated_at__lte=cutoff,
        )
        .filter(
            Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now())
        ).values_list("id", flat=True)
    )
    for payout_id in ids:
        process_single_payout.delay(str(payout_id))
