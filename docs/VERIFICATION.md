# False Green | Developer verification and evidence

This is a **local simulation**, not a reservation service. Its purpose is to reveal a subtle but consequential false-success pattern: HTTP `202 Accepted` is only a queue acknowledgment. The application may still fail before saving a booking. The repair makes the UI reflect **committed** state, not queue acceptance.

## What the judges can inspect

| Stage | Source | What it demonstrates |
|---|---|---|
| 1. Baseline | `git show 1d39c57:app.py` | Initial UI renders **Booking confirmed** after HTTP 202, before worker completion |
| 2. Kane negative | `evidence/closed_loop.json` → `baseline-defect` | Real Kane CLI browser test returned `failed`, reason `assertion_error.confirmed_product_bug`; browser reported premature confirmation visible; independent worker failed and SQLite confirmed-row count was 0 |
| 3. Feedback | `tools/kane_autopilot_v3.py` (`kane_run` → `codex_call`), source hashes and recorded file-read evidence in `evidence/closed_loop.json` | The recorded Sol repair prompt explicitly referenced Kane's baseline NDJSON and the independent oracle; the controller passed those inputs to Sol, without manual prompt relay |
| 4. Code repair | `git diff 1d39c57 372fd4d -- app.py` | Sol replaces immediate confirmation with pending, polling, and terminal states |
| 5. Kane regression | `evidence/closed_loop.json` → `after-fix-failure` and `after-fix-success` | Browser checks passed for rejected and committed outcomes; independent worker/SQLite outcomes agree |
| 6. Review | `evidence/closed_loop.json` → `astra` | Read-only Astra verdict `PASS`, no blocking findings reported |

The original run was executed from a **separate** `kane_competition_autopilot_v3.py` file on November 17, 2026. `tools/kane_autopilot_v3.py` is a source copy of that controller for inspection and **optional, credit-consuming reproduction**. The local private logs and authenticated session folders are not published. The derived public JSON receipt preserves their SHA-256 hashes, verified extracted results, and commit provenance. **Hashes are integrity cross-references, not independent signatures or a substitute for full Kane recordings.** The final video should show the relevant real-browser evidence.

### Actual chain

```
Sol builds (Git 1d39c57)
  ↓
Kane CLI --agent runs a real Chrome flow (FAIL: success shown for failed booking)
  + independent worker/SQLite oracle (failed, 0 saved)
  ↓
Python controller writes the Kane result and passes its log/oracle paths to Sol
  ↓
Sol repairs code (Git 372fd4d)
  ↓
Kane CLI --agent rechecks failure (PASS, 0 saved)
Kane CLI --agent rechecks success (PASS, 1 saved)
  ↓
Astra read-only challenge (PASS)
```

The baseline Kane NDJSON contains one inconsistent natural-language sentence in its summary. We do **not** suppress that. The structured browser observations recorded `booking_confirmed_success_message_visible=true` and `booking_not_confirmed_text_visible=false`, with result code `740`; those facts agree with the original UI code and independent SQLite result. See `evidence/closed_loop.json` for the exact extracted values. The receipt **does not** claim all possible browser flows have been tested.

## Feature map: behavior → user path → evidence

| User-facing behavior | How the user reaches it | Runtime outcome | Deterministic tests | Kane |
|---|---|---|---|---|
| Submit booking | Home → Customer/Date/Time/Party size → Book | API returns 202 + job reference; UI remains pending | `test_acceptance_precedes_persistence`, `test_pending_until_confirmed_status_and_listing` | All 3 flows |
| Booking worker fails | Local QA fail-next (token-gated), then Book | Failed job has no SQLite confirmed record, UI says *Booking not confirmed* | `test_fault_drops_exactly_one_accepted_job_before_persistence`, `test_worker_failure_never_displays_confirmation` | Baseline negative + repaired negative |
| Genuine confirmation | Book without armed fault | Worker commits SQLite, then status becomes confirmed and appears in My Bookings | `test_success_is_committed_and_survives_restart`, `test_pending_until_confirmed_status_and_listing` | Repaired positive |
| Invalid input | Enter invalid data, submit | Server rejects request without consuming fault | `test_validation_rejects_bad_fields`, `test_invalid_submission_does_not_consume_fault` | Not tested by Kane |
| Ambiguous connection | Disconnect after submit / status request error | UI retains unknown/pending; never assumes confirmed | `test_lost_submission_response_is_uncertain`, `test_poll_timeout_keeps_pending` | Not tested by Kane |
| Local QA boundary | Protected `/qa/reset` and `/qa/fail-next` endpoints | Requires token and loopback origin/Host | `test_qa_requires_token_and_rejected_request_does_not_arm_fault`, `test_local_host_and_origin_enforced` | Indirect via controller |
| Worker reset/race | QA reset while job pending | Generation boundary invalidates old jobs | `test_reset_invalidates_inflight_and_queued_jobs_and_disarms_fault` | Not tested by Kane |

A feature map describes **actual** reachable behavior, not speculative features. The demo is local-only, has no accounts, and does not recover queued jobs on restart.

## Run it without Kane or any model

Requirements: Python 3.10+; Node.js optional for frontend regression tests.

```bash
python3 app.py --port 8765
# Open http://127.0.0.1:8765 in a browser
```

In a separate terminal:

```bash
python3 -m unittest discover -s tests -v
python3 tools/verify_chain.py
python3 tools/quality_gate.py
```

`verify_chain.py` checks the public receipt against Git objects and app source. It **does not independently recheck Kane** without the private records. On the originating development machine, use `python3 tools/verify_chain.py --private` to compare the published receipt byte-for-byte with the saved original Kane NDJSON, agent handoff, worker/SQLite oracles, and Astra verdict. These commands require no additional Kane credits.

### Optional full autonomous reproduction (consumes model usage and Kane credits)

The controller is present to show real agent/Kane integration, not to pretend every judge has our private sessions. Install and authenticate the `codex` and `kane-cli` programs first, then test a **fresh, empty folder** separate from this repository. Do not point the full build controller at the reviewed source directory.

```bash
python3 tools/kane_autopilot_v3.py doctor
python3 tools/kane_autopilot_v3.py run --root "$HOME/hackathons/falsegreen-reproduction"
```

The controller invokes separate coding and reviewing model roles; the defaults reflect the original runner. If unavailable, pass supported `--sol` and `--astra` identifiers explicitly. It has bounded calls and will fail closed rather than silently substitute models. Credit thresholds use **observed usage after a run**, not a guaranteed hard spending cap. The included Nov 17 records are evidence of the original run, not proof a fresh invocation will have identical behavior.

## Verification principles

- Use architecture to prevent invalid success states; don't patch over a false green by suppressing the error label.
- Keep guardrails deterministic (database oracles, frontend regression tests, strict receipt parser, Git comparisons).
- Let actual tools execute and debug; a green unit test is not Kane verification.
- Scope the reviewer to evidence, not a permission to rewrite source or invent features.
- Keep one meaningful `AGENTS.md`, focused code and tests, and this single verification map instead of dozens of generated guidance files.
- Do not leak local QA tokens, raw model logs, database, `.testmuai/` sessions, or private controller state to GitHub.

## Human publication gate

Before making this repository public, review `git log --format=fuller` for author name/email, check any Test Manager *share* links and permissions, examine actual screenshots/evidence videos, run the quality gate, and inspect `git ls-files`. This repository deliberately contains **no** original tokenized share URLs. An eventual YouTube demo (3–5 minutes), two distinct public posts, and the official submission form remain separate user-approved actions.

### Commit identity privacy

After the recorded November 17 Kane run, the local commit author and committer emails were replaced with a GitHub noreply address before publication. The Git commit IDs therefore changed. The original baseline and repair source trees, application SHA-256 values, Kane NDJSON, Sol handoff, SQLite oracles, and Astra verdict were not modified. The public receipt points to the metadata-rewritten commits with identical tested application content.
