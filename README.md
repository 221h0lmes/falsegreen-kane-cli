# FALSE GREEN

A carefully scoped local simulation of a realistic asynchronous booking failure. Python's standard library serves a vanilla HTML/CSS/JavaScript interface, runs a real background worker, and saves confirmed bookings in SQLite. No dependencies, credentials, external services, or real reservations.

## Run locally

Requires Python 3.10+ and a modern browser.

```sh
python3 app.py --port 8765
```

Open http://127.0.0.1:8765. The server binds exclusively to `127.0.0.1`. Stop with Ctrl-C. Confirmed bookings persist in `bookings.sqlite3` beside `app.py`; pending and failed job statuses are in memory and expire on restart. A restart does not recover unfinished jobs. My Bookings lists only committed confirmed rows, including records from earlier runs. This local shared demo has no customer accounts; all local bookings appear in that list.

## Current stage: REPAIR — confirmation follows persistence

**HTTP 202 Accepted means queued, not confirmed.** The frontend shows “Booking pending” after acceptance and polls the returned status URL. It renders “Booking confirmed” only when that job reports `confirmed`, after the worker commits the booking to SQLite. A worker failure renders “Booking not confirmed” and never creates a confirmed row or a My Bookings entry.

The backend really queues work, reports pending/failed/confirmed states, and confirms only after the database transaction commits. Fault injection is independent of customer names. Book stays disabled while an accepted request is unresolved, preventing duplicate submissions. Status checks retry transient errors; after three consecutive errors or a minute of polling, the UI keeps the outcome pending and offers “Check booking status” for the same request. A lost submission response displays “Booking status unavailable”; a network error cannot establish whether a booking was saved. Check My Bookings before trying another submission.

The earlier build deliberately confused acceptance with confirmation. The controller independently reproduced that defect before this repair. The separate controller owns Kane's real-browser runs and the independent SQLite oracle. No Kane execution or browser verification is claimed by this repository's unit tests.

## API contract

| Request | Result |
| --- | --- |
| `GET /healthz` | 200 JSON with worker liveness and simulation flag |
| `POST /api/bookings` | 202 JSON: `id`, `status: "pending"`, `status_url` |
| `GET /api/bookings/<id>` | Current job, with `pending`, `failed`, or committed `confirmed` status; 404 for unknown IDs |
| `GET /api/bookings` | `{ "bookings": [...] }`, exclusively confirmed SQLite records |
| `POST /qa/fail-next` | Authenticated local control: arm one job to fail before saving |
| `POST /qa/reset` | Authenticated local control: delete all demo bookings, clear statuses and faults, invalidate queued/in-flight jobs |
| `GET /qa/last-outcome` | Authenticated local read-only observation of the most recently accepted job |

Booking JSON has `customer` (1–100 nonblank characters), `date` (`YYYY-MM-DD`), `time` (`HH:MM`), and integer `party_size` (1–12). The simulation accepts any valid calendar date and time; it does not model venue availability. Invalid input returns 400 and cannot consume a fault. API requests require `Content-Type: application/json` and have an 8 KiB body limit.

Accepted jobs are processed serially by a separate thread with a short delay. Arming reserves failure for exactly the next valid accepted request; repeated arming does not stack faults. Existing queued requests are unaffected. A failed job has no row in `bookings`. SQLite errors also produce failed status, and the worker continues. Reset uses a generation boundary and a shared lock so an old worker cannot restore deleted records after reset.

## Local QA authentication

The server prints a random per-process `X-QA-Token` on startup. Alternatively, set a deliberate local token before starting it:

```sh
export QA_TOKEN='local-demo-only-change-me'
python3 app.py --port 8765
```

In another shell, export that same `QA_TOKEN` (or copy the generated token printed by the server), then:

```sh
curl -sS -X POST http://127.0.0.1:8765/qa/reset \
  -H "X-QA-Token: $QA_TOKEN"
curl -sS -X POST http://127.0.0.1:8765/qa/fail-next \
  -H "X-QA-Token: $QA_TOKEN"
```

Submit customer `KANE-FAIL-2026` in the browser. The UI first shows pending, then “Booking not confirmed”; My Bookings will not contain it. Submit `KANE-OK-2026` without rearming the fault; the UI first shows pending, then “Booking confirmed”, and it will appear in My Bookings. Use Refresh bookings to reload the list.

All routes enforce a loopback peer, a local Host with the listening port, and a matching Origin when supplied. QA mutations additionally require the token; it is never embedded in the page or exposed by an API. No CORS access is enabled. These are local demo controls: do not expose the service with a reverse proxy, tunnel, or public bind.

For an independent, read-only persistence check, Python can inspect the database without requiring a SQLite CLI:

```sh
python3 - <<'PY'
import sqlite3
with sqlite3.connect('file:bookings.sqlite3?mode=ro', uri=True) as db:
    for customer in ('KANE-FAIL-2026', 'KANE-OK-2026'):
        rows = db.execute(
            'SELECT customer, status FROM bookings WHERE customer = ?', (customer,)
        ).fetchall()
        print(customer, rows)
PY
```

After completing both cases with a clean reset, the failure fixture should have no rows and the normal fixture should have one `confirmed` row. Do not reset between the submission and its persistence check.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary databases and real worker threads. The HTTP contract runs through both the real request parser with an in-memory byte transport and real HTTP sockets on ephemeral loopback ports. Environments that prohibit sockets explicitly skip the socket suite; the parser/handler and worker suites still run. They cover durable success, one-job failure, failed-job absence from SQLite, restart persistence, storage errors, validation, concurrent acceptance, reset races, QA authentication, and local-origin protections.

When Node.js is available, unittest also executes the actual inline UI script with Node's built-in VM, a small DOM harness, and controlled fetch/timer boundaries. These regression tests cover pending before terminal status, failure without premature confirmation, successful listing, duplicate-submit prevention, status retries, timeouts, and uncertain network outcomes. They explicitly skip if Node is absent; Node is an optional test tool and is not needed to run the application. Real-browser verification belongs to the controller.
