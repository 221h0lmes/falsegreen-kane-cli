# FALSE GREEN | KaneCLI Hackathon 2026

## Official constraints
- Rules: https://www.kaneclihack.sh/ (read live official rules before submission)
- Any AI coding agent may build; Kane CLI must verify in a REAL browser.
- Site: TestMu AI account with claimed competition credits; submission: public GitHub repository started Nov 12, 2026 or later, YouTube 3-5 min demo, 2 distinct public posts, write-up. Deadline Nov 19, 2026 23:59 IST (= Nov 20, 2026 02:29 PHT).
- Three gate criteria: working E2E app; Kane verified/caught meaningful behavior; agent and Kane results connected in a repair loop. Four equal judging dimensions: Ships, Verified, Closed loop, Craft.

## Build THIS exact small local web application
This is a **clearly disclosed, controlled simulation of a realistic async booking failure**, not an actual reservation business. The bug is authentic at the application behavioral level: HTTP 202/queued is mistaken for durable confirmation. A background worker may drop the accepted job before SQLite persistence, leaving a dishonest success screen.

Implementation constraints: Python standard library only for app server (http.server, sqlite3, threading, etc.), vanilla HTML/CSS/JS; no external APIs or credentials; local-only bind 127.0.0.1; no automated purchases. Start with `python3 app.py --port 8765`. GET /healthz returns 200 and JSON. Persist to ./bookings.sqlite3, table `bookings`, with columns `customer TEXT` and `status TEXT`; a successfully confirmed booking has `status = 'confirmed'`.

Required HTML UX: clearly labeled Customer name, Date, Time, Party size fields; button 'Book'; navigation/action 'My Bookings'; explicit end states 'Booking confirmed' vs 'Booking not confirmed' (render only actual current state). Good styling; honest pending state, accessible labels, realistic microcopy.

Local QA-only endpoints:
- POST /qa/reset: remove fixture bookings and reset fault state; safe exclusively on localhost.
- POST /qa/fail-next: arm one single asynchronous worker job to fail after the API has ACCEPTED it, before persistence; safe on localhost only.
These are deterministic local demo fault controls. Never ship as publicly accessible admin endpoints.

Initial BUILD phase must intentionally retain the realistic defect in the UI ONLY: show 'Booking confirmed' prematurely when HTTP POST /api/bookings responds 202 Accepted, even though the queued worker might still fail. This is not a fake verdict or a bypass: all backend behavior should remain real, and Kane will be asked to verify the full business outcome. Keep the defect only until the Kane negative reproduction is independently observed. No self-written test should falsely report success.

REPAIR phase must correct the actual frontend/backend contract: show pending on 202, poll the booking status reliably, show 'Booking confirmed' ONLY after SQLite persistence and confirmed status, show 'Booking not confirmed' on worker failure. Avoid replacing the app with a hardcoded demo or suppressing the test.

The fixture customer KANE-FAIL-2026 must NOT be stored as a confirmed booking when /qa/fail-next is armed. The normal fixture customer KANE-OK-2026 MUST be stored confirmed and shown in My Bookings. Keep both outcomes independently verifiable from SQLite.

Create app.py, README.md, tests/ with executable unittest tests, requirements-free implementation, and a clear explanation of HTTP 202 vs committed state. Do not include private logs, credentials or claims of real cloud operation in public README.

The controller, not the builder's narrative, runs the authoritative Kane browser checks and SQLite oracle. Do not modify the objective contract or fake output. Do not publish, deploy, submit or purchase.
