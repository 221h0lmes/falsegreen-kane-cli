#!/usr/bin/env python3
"""False Green 2026 v3: contract-adapted Sol -> Kane -> Sol -> Kane -> Astra.

Runs ONLY on the user's computer. Does not publish, deploy, pay, or submit.
The real Kane and Codex integrations have to execute on the user's computer.
Python >=3.10, standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import socket
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT_DEFAULT = Path.home() / "hackathons" / "kanecli-falsegreen-2026"
STAMP = ".kane_autopilot_workspace"
LEGACY_LINE = "Sol is the implementation role through `codex exec`."
TIMESTAMP = lambda: dt.datetime.now(dt.timezone.utc).isoformat()
SEED_FAIL = "KANE-FAIL-2026"
SEED_OK = "KANE-OK-2026"

BRIEF = """# False Green: a KaneCLI Online Hackathon entry

Official competition: https://www.kaneclihack.sh/ (checked 2026-11-17).
Deadline: November 19, 2026 at 23:59 IST = November 20 at 02:29 PHT.
Any coding agent is permitted; real Kane CLI verification is mandatory.
Submission: a public repository initialized on/after November 12, one project
submission, 3–5-minute YouTube video, app and agent description, two distinct
public launch posts. Live URL optional. Must register and claim credits with
same TestMu AI account. Judges need to be able to run the app. Do not publish,
upload, spend money, or submit without the human's approval.
Three minimum bars: actual working application, Kane verifies/catches something,
Kane evidence flows back into an agent repair. Dimensions (25% each): Ships,
Verified, Closed loop, Craft.

## Product, user and real-world failure
False Green is a polished, local-first demonstration for product engineers,
QA engineers and developers of an asynchronous booking confirmation defect:
server returns HTTP 202 Accepted for a queued job but the frontend erroneously
shows "Booking confirmed" before work commits to SQLite. A worker can fail
between acceptance and persistence. That is a real failure mode, simulated with
deterministic failure injection, not a fake Kane verdict. This is NOT a real
booking service; no external providers, customers, credentials or payment APIs.

## Implementation contract
- Python >=3.10 standard library ONLY: http.server/ThreadingHTTPServer,
  sqlite3, threading, json, etc.; vanilla HTML/CSS/JS. No pip/npm app deps.
- Start with `python3 app.py --port 8765`. Bind to 127.0.0.1 ONLY.
- GET /healthz returns 200 JSON with `app: "falsegreen"`, `ok: true`,
  and `instance_id` equal to the current `FALSEGREEN_INSTANCE_ID` process environment
  value. This proves the controller is talking to its OWN newly launched server,
  never an orphaned app from an earlier run.
- DB at ./bookings.sqlite3 has table bookings, `customer TEXT` and
  `status TEXT`; confirmed booking persists status='confirmed'.
- UI fields visibly labeled Customer name, Date, Time, Party size; 'Book'
  action; 'My Bookings' navigation; honest loading/pending state AFTER repair;
  visible exact strings 'Booking confirmed' and 'Booking not confirmed'.
  Basic accessibility, nice CSS, clear user guidance.
- POST /api/bookings responds 202 and returns a job id. A worker asynchronously
  completes the job. GET /api/jobs/<id> lets UI poll pending/confirmed/failed.
  GET /api/bookings lists only actually persisted bookings.
- POST /qa/reset: clears local bookings, resets worker fault and latest-job state.
  POST /qa/fail-next: arms exactly ONE next job to fail after 202, BEFORE
  confirmation persistence. GET /qa/last-outcome returns JSON containing
  `customer`, `status` (pending|confirmed|failed), `accepted` (bool).
  The QA-only endpoints require request header `X-FalseGreen-QA` containing
  the current process environment variable `FALSEGREEN_QA_TOKEN`. On missing
  env token, QA endpoints refuse; no public or internet service. QA tokens
  must not appear in browser HTML/JS or a published README.
- Worker processing should take a short, deterministic delay (~0.5–1s) so
  async acceptance and later failure are visible, with safe SQLite threading.
- The seeded failed booking KANE-FAIL-2026 is never persisted confirmed after
  fault injection; successful KANE-OK-2026 appears exactly once in SQLite
  confirmed and in My Bookings. Use date 2026-12-05, time 19:00, party size 2.

## Two-phase build, with honest outcomes
BUILD intentionally keeps ONE genuine bug in frontend: immediately show
"Booking confirmed" on 202 even though worker might fail. Everything else
must work. The controller's real Kane run is expected to FAIL an assertion
that confirmation should not appear after an injected failure. The controller
separately checks backend failure + absence of a committed booking. Tests must
not disguise this defect or hard-code a test result.
REPAIR fixes actual app: 202 means PENDING, poll the job endpoint, show
"Booking confirmed" only after confirmed/persisted, and show
"Booking not confirmed" if worker fails. Test both paths and race conditions.

## Deliverables and exclusions
- app.py, README.md, tests/test*.py, and any static files actually used.
- unittest discover -s tests must pass, but this does not replace Kane.
- Public README documents install/run, honest scope/limitations and how
  Kane was used, citing only real actual-run evidence once available.
- No real bookings, paid services, production promises or fabricated results.
- No external deployment, repo publication, submission, browser shopping,
  arbitrary file deletion, or modification of the controller/private logs.
"""
AGENTS = """# Critical operating instructions for the ACTIVE coding agent

If invoked by the controller as Sol, you are ALREADY the active coding agent.
**Edit repository files directly with your ordinary file-editing and shell tools.**
If invoked as Astra, you are a READ-ONLY reviewer; never edit source files.
DO NOT invoke `codex`, `codex exec`, another agent, a model API, or a nested
CLI. Never ask another session for permission to implement. You are the
builder, not an orchestrator. A separate Python controller invokes you,
Kane CLI and Astra independently. The controller already has permission to
edit THIS new repository; no external deployments or publishing.

Read PROJECT_BRIEF.md; implement exactly its current stage. Kane is a separate
AI-powered real-browser test, not your replacement coding model. Do not invoke
Kane yourself: the controller owns the Kane run, objectives, and evidence.
Astra is a separate READ-ONLY reviewer invoked by the controller.
Keep the app strictly local-only, use standard-library Python runtime, and run
honest unit tests. Don't alter .kane_autopilot_private or any oracle evidence.
No nested Codex calls, no credentials, no deployment, no publishing.
"""
GITIGNORE = """.kane_autopilot_private/
.kane_autopilot_workspace
__pycache__/
*.py[cod]
*.sqlite3
*.sqlite3-*
.testmuai/
.env
.env.*
.venv/
SUBMISSION_CHECKLIST_PRIVATE.md
"""

class GateError(RuntimeError):
    pass

def report(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def run_cmd(cmd, *, cwd=None, input_text=None, timeout=90, output_base=None, env=None):
    kw = dict(cwd=cwd, text=True, capture_output=True, timeout=timeout, env=env,
              stdin=subprocess.DEVNULL if input_text is None else None)
    if input_text is not None:
        kw.pop("stdin")
        kw["input"] = input_text
    proc = subprocess.run(cmd, **kw)
    if output_base is not None:
        p = Path(output_base)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.with_suffix(".stdout.txt").write_text(proc.stdout, encoding="utf-8")
        p.with_suffix(".stderr.txt").write_text(proc.stderr, encoding="utf-8")
    return proc

def doctor():
    report("Preflight checks: no models or Kane browser runs yet...")
    missing = [k for k in ("python3", "node", "npm", "git", "codex", "kane-cli") if not shutil.which(k)]
    if missing:
        raise GateError("Missing executables: " + ", ".join(missing))
    if sys.version_info < (3, 10):
        raise GateError("Python >=3.10 required")
    for command in (["codex", "--version"], ["kane-cli", "--version"],
                    ["node", "--version"], ["git", "--version"]):
        out = run_cmd(command, timeout=20)
        if out.returncode:
            raise GateError("Doctor command failed: " + " ".join(command))
        version = (out.stdout or out.stderr).strip()
        report("  " + command[0] + ": " + version[:110])
        if command[0] == "node":
            m = re.match(r"v?(\d+)", version)
            if not m or int(m.group(1)) < 18:
                raise GateError("Node >=18 required")
    if run_cmd(["kane-cli", "whoami"], timeout=25).returncode:
        raise GateError("Kane not authenticated; run `kane-cli login` interactively")
    if run_cmd(["codex", "login", "status"], timeout=25).returncode:
        raise GateError("Codex not authenticated; run `codex login`")
    if not any(shutil.which(k) for k in ("google-chrome", "google-chrome-stable", "chromium")):
        raise GateError("Chrome/Chromium executable is required for local Kane web tests")
    report("Doctor PASS (only installed tools and authentication verified)")

def state_path(private):
    return private / "state.json"

def load_state(private):
    f = state_path(private)
    if f.exists():
        value = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("completed"), list):
            raise GateError("Invalid saved state; refusing to reset budgets")
        return value
    return dict(created=TIMESTAMP(), completed=[], credits_observed=0., kane_runs=0, model_calls=0)

def save_state(private, state):
    state["updated"] = TIMESTAMP()
    p = state_path(private)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)

def git_checkpoint(root, name, mandatory=True):
    if run_cmd(["git", "add", "-A"], cwd=root).returncode:
        raise GateError("git add failed during " + name)
    if run_cmd(["git", "diff", "--cached", "--quiet"], cwd=root).returncode == 0:
        return
    result = run_cmd(["git", "commit", "-m", name], cwd=root)
    if result.returncode and mandatory:
        raise GateError("git commit failed: " + result.stderr[-900:])

def prepare(root):
    if root.exists() and any(root.iterdir()) and not (root / STAMP).exists():
        raise GateError("Non-autopilot directory; refusing to modify: " + str(root))
    root.mkdir(parents=True, exist_ok=True)
    (root / STAMP).touch(exist_ok=True)
    private = root / ".kane_autopilot_private"
    private.mkdir(exist_ok=True)
    if not (root / "PROJECT_BRIEF.md").exists():
        (root / "PROJECT_BRIEF.md").write_text(BRIEF, encoding="utf-8")
    agents = root / "AGENTS.md"
    if not agents.exists():
        agents.write_text(AGENTS, encoding="utf-8")
    else:
        old = agents.read_text(encoding="utf-8")
        if LEGACY_LINE in old:
            # Upgrade only the exactly recognized legacy controller AGENTS.md;
            # preserve the original as private evidence instead of overwriting user edits.
            prior = "# Local autonomous build instructions\n" + LEGACY_LINE
            if not old.startswith(prior):
                raise GateError("AGENTS.md contains legacy nested-Codex direction and unknown edits. Refusing blind overwrite")
            old_target = private / "AGENTS.legacy.run1.md"
            if not old_target.exists():
                old_target.write_text(old, encoding="utf-8")
            agents.write_text(AGENTS, encoding="utf-8")
            report("Replaced legacy AGENTS.md nested-Codex instruction (original privately backed up)")
        elif "DO NOT invoke `codex`" not in old:
            raise GateError("Unrecognized AGENTS.md; refusing to assume it prevents nested Codex calls")
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")
    else:
        oldignore = ignore.read_text(encoding="utf-8")
        if "SUBMISSION_CHECKLIST_PRIVATE.md" not in oldignore:
            ignore.write_text(oldignore.rstrip() + "\nSUBMISSION_CHECKLIST_PRIVATE.md\n", encoding="utf-8")
    if not (root / ".git").exists():
        init = run_cmd(["git", "init", "-b", "main"], cwd=root)
        if init.returncode:
            raise GateError("git init failed: " + init.stderr[-900:])
        git_checkpoint(root, "Initialize False Green project")
    return private

def finish(private, state, name, root, details):
    git_checkpoint(root, name)
    if name not in state["completed"]:
        state["completed"].append(name)
    save_state(private, state)
    report(f"PASS {name}: {details}")

def codex_call(root, private, state, *, model, stage, instruction, reviewer, cap):
    if state["model_calls"] >= cap:
        raise GateError(f"Model call budget exhausted ({state['model_calls']}/{cap}); no reset")
    state["model_calls"] += 1
    save_state(private, state)
    base = private / f"{state['model_calls']:02d}_{stage}"
    base.with_suffix(".prompt.txt").write_text(instruction, encoding="utf-8")
    cmd = ["codex", "exec", "--model", model, "--sandbox", "read-only" if reviewer else "workspace-write",
           "--cd", str(root), "--output-last-message", str(base.with_suffix(".last.txt")), "-"]
    report(f"Calling {stage} as {model} (logs: {base.name})")
    try:
        result = run_cmd(cmd, cwd=root, input_text=instruction, timeout=1800 if reviewer else 2700, output_base=base)
    except subprocess.TimeoutExpired as err:
        raise GateError(f"{stage} timed out. Inspect its session state before retrying") from err
    if result.returncode:
        raise GateError(f"{stage} CLI rc={result.returncode}; check {base}.stderr.txt. No model substitution")
    path = base.with_suffix(".last.txt")
    return path.read_text(encoding="utf-8") if path.exists() else result.stdout

def tests_run(root, private, tag):
    tests = root / "tests"
    if not tests.is_dir() or not any(tests.glob("test*.py")):
        raise GateError("Missing tests/test*.py; build contract not fulfilled")
    out = run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                  cwd=root, timeout=240, output_base=private / f"unit_{tag}")
    if out.returncode:
        raise GateError(f"Unit tests failed ({tag}); see unit_{tag}.stderr.txt")
    report("Unit tests PASSED: " + tag)

def http_request(base, path, *, method="GET", token=None, body=None, timeout=8):
    h = {"Content-Type": "application/json"}
    if token:
        h["X-QA-Token"] = token
    payload = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(base + path, data=payload, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as reply:
            if not (200 <= reply.status < 300):
                raise GateError(f"{method} {path}: unexpected status {reply.status}")
            return reply.status, json.loads(reply.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        raise GateError(f"HTTP {method} {path} failed: {err}") from err

class Server:
    def __init__(self, root, private, port):
        self.root, self.private, self.port = root, private, port
        self.base = f"http://127.0.0.1:{port}"
        self.qa_token = secrets.token_urlsafe(24)
        self.instance_id = secrets.token_urlsafe(24)
        self.proc, self.stream = None, None

    def __enter__(self):
        if not (self.root / "app.py").exists():
            raise GateError("Missing app.py; build incomplete")
        # An orphaned earlier app may occupy the requested port. Never attach
        # to it or send it a fresh QA token. Choose a free alternate instead.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            occupied = probe.connect_ex(("127.0.0.1", self.port)) == 0
        if occupied:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
                holder.bind(("127.0.0.1", 0))
                self.port = holder.getsockname()[1]
            self.base = f"http://127.0.0.1:{self.port}"
            report(f"Requested port occupied; picked local free port {self.port} (will verify instance identity)")
        self.stream = (self.private / "app-server.log").open("a", encoding="utf-8")
        env = os.environ.copy()
        env["QA_TOKEN"] = self.qa_token
        env["FALSEGREEN_INSTANCE_ID"] = self.instance_id
        self.proc = subprocess.Popen([sys.executable, "app.py", "--port", str(self.port)],
                                     cwd=self.root, stdin=subprocess.DEVNULL, stdout=self.stream,
                                     stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            for _ in range(100):
                if self.proc.poll() is not None:
                    raise GateError(f"App exited rc={self.proc.returncode}; inspect app-server.log")
                try:
                    _, result = http_request(self.base, "/healthz", timeout=0.3)
                    if (result.get("app") == "falsegreen" and result.get("ok") is True
                            and result.get("instance_id") == self.instance_id):
                        return self
                    raise GateError("App health response is incompatible or has wrong instance_id: " + str(result)[:250])
                except GateError as err:
                    last_error = str(err)
                    time.sleep(0.15)
            raise GateError("Cannot verify OUR app at /healthz: " + locals().get('last_error', 'no response')
                            + "; inspect .kane_autopilot_private/app-server.log")
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_):
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait(timeout=6)
        if self.stream:
            self.stream.close()

def qa(server, path, method="POST"):
    return http_request(server.base, path, token=server.qa_token, method=method)[1]

def check_job(server, name, expected, deadline=12):
    end = time.monotonic() + deadline
    data = {}
    while time.monotonic() < end:
        data = qa(server, "/qa/last-outcome", "GET")
        if data.get("customer") == name and data.get("status") == expected and data.get("accepted") is True:
            return data
        time.sleep(0.35)
    raise GateError(f"Independent job oracle missing {name}/{expected}; last outcome={data!r}")

def smoke_test(server, root):
    """Exercise actual Sol-built worker and durable SQLite before any Kane calls."""
    qa(server, "/qa/reset")
    initial = qa(server, "/qa/last-outcome", "GET")
    if initial.get("accepted") is not False:
        raise GateError("QA reset did not clear last accepted booking")
    qa(server, "/qa/fail-next")
    name = "V3-SMOKE-FAIL"
    status, reply = http_request(server.base, "/api/bookings", method="POST", body={
        "customer": name, "date": "2026-12-05", "time": "19:00", "party_size": 2})
    if status != 202 or reply.get("status") != "pending":
        raise GateError("Smoke failure booking did not receive HTTP 202 pending")
    check_job(server, name, "failed")
    if confirmed(root, name) != 0:
        raise GateError("Smoke failure was incorrectly persisted")
    qa(server, "/qa/reset")
    name = "V3-SMOKE-SUCCESS"
    status, reply = http_request(server.base, "/api/bookings", method="POST", body={
        "customer": name, "date": "2026-12-05", "time": "19:00", "party_size": 2})
    if status != 202 or reply.get("status") != "pending":
        raise GateError("Smoke success booking did not receive HTTP 202 pending")
    check_job(server, name, "confirmed")
    if confirmed(root, name) != 1:
        raise GateError("Smoke success booking was not durably confirmed exactly once")
    qa(server, "/qa/reset")
    if confirmed(root, name) != 0:
        raise GateError("QA reset failed to clear smoke booking")
    report("Local worker+SQLite preflight PASS: real failed and confirmed jobs (no Kane credits)")

def confirmed(root, customer):
    db = root / "bookings.sqlite3"
    if not db.exists():
        raise GateError("SQLite DB missing: independent persistence proof unavailable")
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=8) as c:
        return int(c.execute("SELECT count(*) FROM bookings WHERE customer=? AND status='confirmed'", (customer,)).fetchone()[0])

def read_events(stdout):
    events = []
    for line in stdout.splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except json.JSONDecodeError:
            pass
    return events

def validate_kane(events, rc, expected):
    """Fail closed on infra failures, absent run_end, ambiguous baseline failures."""
    end = next((x for x in reversed(events) if x.get("type") == "run_end"), None)
    if end is None:
        raise GateError("Kane emitted no run_end event (infra/configuration/timeout possible)")
    status = str(end.get("status", "unknown")).lower()
    code_raw = end.get("result_code")
    try:
        code = int(code_raw) if code_raw is not None else None
    except (TypeError, ValueError):
        code = None
    if rc in (2, 3) or (code is not None and (200 <= code < 700)):
        raise GateError(f"Kane infrastructure/blocked run: rc={rc} result_code={code} status={status}")
    if expected == "pass":
        if rc != 0 or status != "passed" or (code is not None and code >= 700):
            raise GateError(f"Kane expected PASS, got rc={rc} status={status}, code={code}")
    elif expected == "defect":
        if rc != 1 or status != "failed":
            raise GateError(f"No Kane assertion failure on baseline: rc={rc} status={status} code={code}")
        # An upload refusal can be exit code 1 with a run_end; NOT a product bug.
        desc = " ".join(str(end.get(k, "")) for k in ("summary", "reason", "one_liner", "message"))
        failed = [e for e in events if e.get("status") == "failed"]
        desc += " " + " ".join(str(e.get(k, "")) for e in failed for k in ("remark", "message", "reason"))
        if re.search(r"upload|credential|auth|network|billing|quota|chrome failed", desc, re.I):
            raise GateError("Kane baseline failed for infrastructure/upload, NOT a product defect")
        if code is not None and not (700 <= code < 800):
            raise GateError(f"Kane baseline result code {code} is not an assertion/bug class")
        if code is None and not failed:
            raise GateError("Kane baseline lacks result code AND failed-step evidence")
        if not re.search(r"booking|confirm|success|assert|expect|verified|verification", desc, re.I):
            raise GateError("Kane baseline failed, but reason doesn't establish booking assertion")
    else:
        raise ValueError("unknown Kane expectation")
    return end

def kane_run(server, private, state, objective, label, expected, args):
    if state["kane_runs"] >= args.max_kane_runs:
        raise GateError(f"Kane run count exhausted ({state['kane_runs']}/{args.max_kane_runs})")
    if state["credits_observed"] >= args.credit_budget:
        raise GateError(f"Observed Kane credits {state['credits_observed']}; budget {args.credit_budget} reached")
    state["kane_runs"] += 1
    save_state(private, state)
    base = private / f"kane_{state['kane_runs']:02d}_{label}"
    base.with_suffix(".objective.txt").write_text(objective, encoding="utf-8")
    cmd = ["kane-cli", "run", objective, "--url", server.base, "--headless", "--agent",
           "--timeout", "240", "--max-steps", "35", "--final-validation", "on",
           "--mode", "action", "--bug-detection", "off"]
    report(f"Kane actual-browser test {state['kane_runs']} ({label}), expected={expected}")
    try:
        out = run_cmd(cmd, cwd=server.root, timeout=280, output_base=base)
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"Kane {label} timed out; did not mark as verified") from exc
    events = read_events(out.stdout)
    end = next((x for x in reversed(events) if x.get("type") == "run_end"), None)
    if end is not None:
        used = end.get("credits_consumed", end.get("credits"))
        if isinstance(used, (int, float)):
            state["credits_observed"] += max(0, float(used))
    save_state(private, state)
    try:
        validate_kane(events, out.returncode, expected)
    except GateError as err:
        raise GateError(f"{err}; inspect {base}.stdout.txt/.stderr.txt") from err
    return end

def objective(name, failure, base):
    flow = (f"Use the browser at {base}. Fill Customer name with {name}, Date with 2026-12-05, "
            "Time with 19:00, and Party size with 2. Press Book ONCE. "
            "Wait at least 3 seconds after submission to allow asynchronous worker completion. ")
    if failure:
        return flow + ("Assert that there is NO visible 'Booking confirmed' success message anywhere "
                       "in the final UI, and that visible text 'Booking not confirmed' IS shown. "
                       "Treat a success confirmation as a FAILING assertion; do not just report "
                       "the UI looks attractive. Do not reset, bypass, or repair the app.")
    return flow + ("Assert visible 'Booking confirmed'; open My Bookings, and assert "
                   f"{name} is listed as confirmed. Treat an absent entry as FAILURE.")

def astra_json(text):
    txt = text.strip()
    if txt.startswith("```"):
        txt = "\n".join(txt.splitlines()[1:-1]).strip()
    try:
        data = json.loads(txt)
    except ValueError as ex:
        raise GateError("Astra did not return strict JSON") from ex
    if not isinstance(data, dict) or data.get("verdict") not in ("PASS", "REVISE") or not isinstance(data.get("findings"), list):
        raise GateError("Invalid Astra schema")
    for item in data["findings"]:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip()
            for k in ("id", "severity", "evidence", "remediation")) or item["severity"] not in ("blocking", "nonblocking"):
            raise GateError("Invalid Astra finding")
    blockers = any(x["severity"] == "blocking" for x in data["findings"])
    if (data["verdict"] == "PASS") == blockers:
        raise GateError("Inconsistent Astra verdict and blocking findings")
    return data

# SHA256 of the Sol-built app.py supplied in the November 17 v2 diagnostics.
# Never silently patch an unfamiliar app or an in-progress human edit.
V2_SOL_APP_SHA256 = "ecd2c97901939510b61e10feae3d5d7b4dfc62fc46330eb5ad493f54ad929171"
V3_APP_MARKER = "# FALSEGREEN_V3_CONTRACT"

def contract_patch_source(original):
    """Narrow, deterministic compatibility patch for the SPECIFIC Sol-built application."""
    actual = hashlib.sha256(original.encode("utf-8")).hexdigest()
    if actual != V2_SOL_APP_SHA256:
        raise GateError("Refusing unknown app.py version. Expected v2 Sol SHA256 "
                        + V2_SOL_APP_SHA256 + ", found " + actual
                        + ". No files changed; preserve or review human edits before patching.")
    patches = [
        ('        self.jobs = {}\n', '        self.jobs = {}\n        self.last_job_id = None\n'),
        ('            self.jobs[job_id] = job\n', '            self.jobs[job_id] = job\n            self.last_job_id = job_id\n'),
        ('            self.jobs.clear()\n', '            self.jobs.clear()\n            self.last_job_id = None\n'),
        ('    def bookings(self):\n', """    def last_outcome(self):
        # Private read-only observation; failed jobs never create SQLite rows.
        with self.lock:
            job = self.status(self.last_job_id) if self.last_job_id else None
            if not job:
                return {"customer": None, "status": "none", "accepted": False}
            return {"customer": job["customer"], "status": job["status"],
                    "accepted": True, "id": job["id"]}

    def bookings(self):
"""),
        ('        self.service, self.qa_token = service, qa_token\n',
         '        self.service, self.qa_token = service, qa_token\n        self.instance_id = os.environ.get("FALSEGREEN_INSTANCE_ID", "")\n'),
        ('        elif path == "/healthz":\n            self._send(200, {"ok": self.server.service.worker.is_alive(), "simulation": True})\n',
         """        elif path == "/healthz":
            # FALSEGREEN_V3_CONTRACT: fresh server identity prevents stale-process results.
            self._send(200, {"app": "falsegreen", "ok": self.server.service.worker.is_alive(),
                             "simulation": True, "instance_id": getattr(self.server, "instance_id", "")})
        elif path == "/qa/last-outcome":
            provided = self.headers.get("X-QA-Token", "")
            if not hmac.compare_digest(provided.encode(), self.server.qa_token.encode()):
                self._send(401, {"error": "QA authentication required."})
                return
            self._send(200, self.server.service.last_outcome())
""")
    ]
    edited = original
    for old, replacement in patches:
        if edited.count(old) != 1:
            raise GateError("Cannot safely patch app contract: missing or ambiguous snippet " + repr(old[:90]))
        edited = edited.replace(old, replacement, 1)
    return edited

V2_SOL_TEST_SHA256 = "4f5853e72b2c56aa32a4dd51f45d64ff3016bfe8cd7867901dfc4ff8fcf25ae2"

def reconcile_v2_sol_tests(root, private):
    """Update exactly one legacy health assertion to check the stronger v3 identity."""
    p = root / "tests" / "test_app.py"
    if not p.exists():
        return False
    original = p.read_text(encoding="utf-8")
    if '"instance_id": ""' in original and '"app": "falsegreen"' in original:
        return False
    if hashlib.sha256(original.encode("utf-8")).hexdigest() != V2_SOL_TEST_SHA256:
        # Never rewrite unknown tests silently. They will be run normally and
        # any incompatible assertion will fail with an actionable traceback.
        return False
    old = 'self.assertEqual(data, {"ok": True, "simulation": True})'
    new = ('self.assertEqual(data, {"app": "falsegreen", "ok": True, '
           '"simulation": True, "instance_id": ""})')
    if original.count(old) != 1:
        raise GateError("Legacy health assertion not found exactly once")
    backup = private / "test_app.v2_original.py"
    if backup.exists() and backup.read_text(encoding="utf-8") != original:
        raise GateError("Existing original test backup differs; refusing to overwrite")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    stage = private / "test_app.v3.stage.py"
    stage.write_text(original.replace(old,new), encoding="utf-8")
    stage.replace(p)
    report("Updated one strict health-unit-test assertion for v3, original backed up")
    return True

def reconcile_v2_sol_contract(root, private):
    """Patch only known app contract, backing up exact bytes once, fail closed otherwise."""
    path = root / "app.py"
    if not path.is_file():
        raise GateError("Sol app.py not present; cannot reconcile")
    original = path.read_text(encoding="utf-8")
    if V3_APP_MARKER in original:
        for fragment in ('"/qa/last-outcome"', '"FALSEGREEN_INSTANCE_ID"', '"X-QA-Token"'):
            if fragment not in original:
                raise GateError("Partial or damaged v3 app contract; no automatic overwrite")
        report("App contract already adapted; preserving existing v3 application")
        return False
    new = contract_patch_source(original)
    backup = private / "app.v2_sol_original.py"
    if backup.exists() and backup.read_text(encoding="utf-8") != original:
        raise GateError("Existing original-app backup differs; refusing overwrite")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    staged = private / "app.v3.stage.py"
    staged.write_text(new, encoding="utf-8")
    try:
        compile(new, str(path), 'exec')
    except SyntaxError as error:
        staged.unlink(missing_ok=True)
        raise GateError("Contract patch failed syntax check; original preserved") from error
    staged.replace(path)
    report("Adapted existing Sol app contract (original privately backed up; no Sol call)")
    return True

def perform_gate(root, private, state, args):
    # v2 state has two genuine Sol calls, no Kane runs, and app/tests already exist.
    # The expected resume must not buy another initial build/model call.
    if "build" not in state["completed"]:
        ready = ((root / "app.py").is_file() and (root / "README.md").is_file()
                 and (root / "tests").is_dir() and any((root / "tests").glob("test*.py")))
        if not ready:
            # Remain compatible with a first-time fresh workspace, but do not
            # waste calls when real Sol deliverables already exist.
            for attempt in range(2):
                response = codex_call(root, private, state, model=args.sol,
                    stage="sol-build" if attempt == 0 else "sol-build-recovery",
                    instruction=("YOU ARE SOL, THE ACTIVE CODING AGENT. Edit files DIRECTLY, never invoke a nested agent/CLI. "
                      "Read PROJECT_BRIEF.md and AGENTS.md. Build the app.py, README.md and tests, with an "
                      "asynchronous booking worker, genuine 202 false-success UI bug, and authenticated QA endpoints. "
                      "Preserve exact v3 QA contract: GET /healthz returns app=falsegreen, ok=true, "
                      "instance_id from FALSEGREEN_INSTANCE_ID; QA header X-QA-Token sourced from QA_TOKEN; "
                      "GET /qa/last-outcome authenticated returns customer, status and accepted; "
                      "POST /qa/reset and /qa/fail-next. Never run Kane, Codex or publish anything."),
                    reviewer=False, cap=args.max_model_calls)
                ready = ((root / "app.py").is_file() and (root / "README.md").is_file()
                         and (root / "tests").is_dir() and any((root / "tests").glob("test*.py")))
                if ready:
                    break
                (private / f"build_missing_attempt_{attempt+1}.txt").write_text(response[-5000:], encoding="utf-8")
            if not ready:
                raise GateError("Sol returned without app/files after bounded attempts")
        else:
            report("Found existing Sol-built app and tests; NOT invoking another build model")
        # The exact Nov 17 uploaded app needs a narrow adapter. Unknown apps
        # are never automatically edited to match an assumed contract.
        app_text = (root / "app.py").read_text(encoding="utf-8")
        if hashlib.sha256(app_text.encode("utf-8")).hexdigest() == V2_SOL_APP_SHA256 or V3_APP_MARKER in app_text:
            reconcile_v2_sol_contract(root, private)
            reconcile_v2_sol_tests(root, private)
        tests_run(root, private, "build")
        with Server(root, private, args.port) as server:
            smoke_test(server, root)
        finish(private, state, "build", root, "real worker fail/success, app identity, authenticated QA and SQLite PASS")

    if "bug_reproduced" not in state["completed"]:
        with Server(root, private, args.port) as server:
            qa(server, "/qa/reset")
            qa(server, "/qa/fail-next")
            result = kane_run(server, private, state, objective(SEED_FAIL, True, server.base),
                              "baseline-defect", "defect", args)
            job = check_job(server, SEED_FAIL, "failed")
            n = confirmed(root, SEED_FAIL)
            if n != 0:
                raise GateError(f"Baseline defect oracle unexpected committed booking: {n}")
            (private / "bug_repro_oracle.json").write_text(json.dumps({"kane":result, "job":job, "db_confirmed":n}, indent=2), encoding="utf-8")
        finish(private, state, "bug_reproduced", root, "Kane detected faulty confirmation AND independent job/SQLite oracles agreed")

    if "repair" not in state["completed"]:
        codex_call(root, private, state, model=args.sol, stage="sol-repair", reviewer=False,
                   instruction=("YOU ARE SOL; edit files DIRECTLY. Do NOT call nested Codex. "
                                "Read PROJECT_BRIEF.md, .kane_autopilot_private/bug_repro_oracle.json "
                                "and matching kane_*_baseline-defect.stdout.txt. Kane detected the premature 'Booking confirmed' UI "
                                "on a genuinely failed worker job. Fix it: show pending on HTTP 202, poll real job status, "
                                "show confirmed ONLY after durable persistence and show 'Booking not confirmed' on failure. "
                                "Keep the backend real, QA fault injection and authenticated local endpoints. Add regression "
                                "tests; do not edit private evidence or weaken expected behavior. Run tests. Do not publish."),
                   cap=args.max_model_calls)
        tests_run(root, private, "repair")
        finish(private, state, "repair", root, "repaired app passes local unit tests")

    for stage, name, fail in (("negative_verified", SEED_FAIL, True), ("positive_verified", SEED_OK, False)):
        if stage in state["completed"]:
            continue
        with Server(root, private, args.port) as server:
            qa(server, "/qa/reset")
            if fail:
                qa(server, "/qa/fail-next")
            kane_end = kane_run(server, private, state, objective(name, fail, server.base),
                               "after-fix-failure" if fail else "after-fix-success", "pass", args)
            job = check_job(server, name, "failed" if fail else "confirmed")
            count = confirmed(root, name)
            if count != (0 if fail else 1):
                raise GateError(f"{stage} database oracle mismatch: count={count}")
            (private / f"{stage}_oracle.json").write_text(json.dumps({"kane":kane_end, "job":job, "db_confirmed":count}, indent=2), encoding="utf-8")
        finish(private, state, stage, root, f"Kane browser PASS and job+SQLite oracle count={count}")

    if "astra_review" not in state["completed"]:
        prompt = ("Astra: READ-ONLY ADVERSARIAL REVIEW. Do not modify or run nested Codex. "
                  "Review actual PROJECT_BRIEF.md, app.py, README.md, tests, "
                  ".kane_autopilot_private/bug_repro_oracle.json, "
                  ".kane_autopilot_private/negative_verified_oracle.json, "
                  ".kane_autopilot_private/positive_verified_oracle.json. "
                  "Challenge authentication, QA endpoint safety, async race correctness, database integrity, test oracle validity, "
                  "Kane evidence, prompt injection, UX and unsupported claims. Only evidence-backed BLOCKING findings. "
                  "Return ONLY strict JSON: {\"verdict\":\"PASS\" or \"REVISE\",\"findings\":[{\"id\":\"...\",\"severity\":\"blocking\" "
                  "or \"nonblocking\",\"evidence\":\"path:line or observed result\",\"remediation\":\"specific fix\"}]}. "
                  "PASS if and only if there are no blocking findings. Do not claim to have tested what you did not execute.")
        review = astra_json(codex_call(root, private, state, model=args.astra, stage="astra-review", instruction=prompt,
                                       reviewer=True, cap=args.max_model_calls))
        (private / "astra_verdict.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
        if review["verdict"] == "REVISE":
            report("Astra found blockers; carrying verified findings to Sol once")
            codex_call(root, private, state, model=args.sol, stage="sol-astra-fix", reviewer=False,
                       instruction=("YOU ARE SOL. Edit code directly, never nested Codex. "
                                    "Fix specific evidence-backed BLOCKING findings in .kane_autopilot_private/astra_verdict.json. "
                                    "Do not alter Kane objectives, QA behavior or private evidence. Keep working app and regression tests. "
                                    "Run unittest. No publishing."), cap=args.max_model_calls)
            tests_run(root, private, "astra-fix")
            # Crucial: re-run both real Kane flows after ANY Astra-induced code changes.
            for name, fail in ((SEED_FAIL, True), (SEED_OK, False)):
                with Server(root, private, args.port) as server:
                    qa(server, "/qa/reset")
                    if fail:
                        qa(server, "/qa/fail-next")
                    kane_run(server, private, state, objective(name, fail, server.base),
                             "regression-failure" if fail else "regression-success", "pass", args)
                    check_job(server, name, "failed" if fail else "confirmed")
                    if confirmed(root, name) != (0 if fail else 1):
                        raise GateError("Post-Astra repair persistence regression")
            rereview = astra_json(codex_call(root, private, state, model=args.astra, stage="astra-rereview", reviewer=True,
                          instruction=("Astra READ-ONLY: verify every original blocker in .kane_autopilot_private/astra_verdict.json "
                                       "is resolved by code AND current regression evidence. Return ONLY strict JSON with same "
                                       "verdict/findings schema; no nested agents, no edits."), cap=args.max_model_calls))
            (private / "astra_rereview.json").write_text(json.dumps(rereview, indent=2), encoding="utf-8")
            if rereview["verdict"] != "PASS":
                raise GateError("Astra re-review did not pass; stopped instead of faking green")
        finish(private, state, "astra_review", root, "independent read-only Astra challenge resolved")

    checklist = root / "SUBMISSION_CHECKLIST_PRIVATE.md"
    if not checklist.exists():
        checklist.write_text("""# Human submission gate: NOT YET SUBMITTED
- [ ] Review source, Kane browser run_end NDJSON, screenshots/evidence packs and Git history.
- [ ] Confirm baseline failed on intended UI assertion, not merely infra; review actual post-fix replays.
- [ ] Confirm real app still meets new-user setup + README; no private logs/QA secrets in public repo.
- [ ] Confirm TestMu AI registration and claimed hackathon credits use same email.
- [ ] Create a public GitHub repo from THIS post-Nov12 code/history, no source from before the event.
- [ ] Record real 3–5-minute YouTube demo with Kane failure, feedback to Sol, fix and passing checks.
- [ ] Write two distinct public promotional posts (X/Reddit/HN/LinkedIn).
- [ ] Fill official hackathon submission form before 2026-11-19 23:59 IST (2026-11-20 02:29 PHT).
- [ ] No exaggerated 'production grade' or real payment/booking claims.
- [ ] Manual final approval required. Controller cannot submit/publish.
""", encoding="utf-8")
    report("LOCAL PIPELINE COMPLETED; NOT published, deployed or submitted")
    report("Project: " + str(root))
    report("Private evidence: " + str(private))
    report(f"Kane credits reported by runs (not wallet balance): {state['credits_observed']:.2f}")

def main(argv=None):
    p = argparse.ArgumentParser(description="Bounded one-command KaneCLI hackathon workflow v3")
    p.add_argument("action", nargs="?", choices=("doctor", "run"), default="doctor")
    p.add_argument("--root", type=Path, default=ROOT_DEFAULT)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--sol", default="gpt-6.1-sol")
    p.add_argument("--astra", default="gpt-6-astra")
    p.add_argument("--max-model-calls", type=int, default=6)
    p.add_argument("--max-kane-runs", type=int, default=6)
    p.add_argument("--credit-budget", type=float, default=400.0,
                   help="Observed cumulative Kane usage only; cannot cap an in-flight run")
    a = p.parse_args(argv)
    if not (1 <= a.port <= 65535) or a.max_model_calls < 1 or a.max_kane_runs < 1 or a.credit_budget <= 0:
        p.error("Invalid port or budget")
    try:
        if a.action == "doctor":
            doctor()
        else:
            doctor()
            root = a.root.expanduser().resolve()
            private = prepare(root)
            state = load_state(private)
            report(f"Resuming from gates={state['completed']}, existing model_calls={state['model_calls']}, "
                   f"kane_runs={state['kane_runs']}; budgets preserved")
            save_state(private, state)
            perform_gate(root, private, state, a)
    except (GateError, OSError, sqlite3.Error, ValueError, subprocess.TimeoutExpired) as err:
        report("STOPPED SAFELY: " + str(err))
        report("No deployment, publishing, purchase or submission. Investigate evidence before retrying.")
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
