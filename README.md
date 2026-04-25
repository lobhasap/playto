# Playto Payout Engine

Django + DRF backend and React + Tailwind dashboard for merchant balances and payout processing with money-safe ledgering, idempotency, and concurrency control.

## Tech Stack

- Backend: Django, DRF, Celery
- Frontend: React, Vite, Tailwind CSS
- Database: PostgreSQL (primary), SQLite optional for local tests
- Queue: Redis

## Backend Setup

```bash
cd backend
python -m venv ../.venv
../.venv/Scripts/pip install -r requirements.txt
```

Set environment variables (example):

- `POSTGRES_DB=payout_engine`
- `POSTGRES_USER=postgres`
- `POSTGRES_PASSWORD=postgres`
- `POSTGRES_HOST=localhost`
- `POSTGRES_PORT=5432`
- `CELERY_BROKER_URL=redis://localhost:6379/0`
- `CELERY_RESULT_BACKEND=redis://localhost:6379/1`

Run app:

```bash
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Run worker + beat:

```bash
celery -A payout_engine worker -l info
celery -A payout_engine beat -l info
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend expects API at `http://127.0.0.1:8000/api/v1`.

## API Endpoints

- `GET /api/v1/merchants`
- `GET /api/v1/merchants/{merchant_id}/dashboard`
- `POST /api/v1/payouts` (requires `Idempotency-Key` header UUID)
- `GET /api/v1/merchants/{merchant_id}/payouts`

Sample payout request:

```json
{
  "merchant_id": 1,
  "amount_paise": 6000,
  "bank_account_id": 1
}
```

Idempotency behavior:
- Keys are scoped per merchant and cached in `IdempotencyRecord`.
- Repeating the same key within 24 hours returns the exact same response payload/status as the first request.
- Expiry removes only idempotency cache rows, not payout/ledger records.

## Tests

```bash
cd backend
set USE_SQLITE=true
set CELERY_TASK_ALWAYS_EAGER=true
../.venv/Scripts/python manage.py test payouts
```

Includes:
- idempotency replay test
- concurrent payout contention test

PostgreSQL recommendation for final verification:
- Run tests against PostgreSQL to validate row-level lock semantics (`SELECT ... FOR UPDATE`) exactly.
- In PostgreSQL mode, the concurrency test expects exactly one `201` and one `400` for two simultaneous `6000`-paise requests on a `10000`-paise balance.

## Notes

- Money is stored in paise as `BigIntegerField`.
- Balances are computed through DB aggregation and ledger entries only.
- Payout state transitions are enforced by a state machine guard in the model.
