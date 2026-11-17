#!/usr/bin/env python3
"""Verify the False Green Kane→Sol evidence chain. No model/Kane calls.

The default/public check verifies a sanitized receipt against the Git commits
and application code. --private requires original local Kane NDJSON and agent
handoff logs, then reconstructs and compares the receipt byte-for-byte.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

RUNS = (
    ("baseline-defect", "kane_01_baseline-defect.stdout.txt", "bug_repro_oracle.json", "failed", "failed", 0, "assertion_error.confirmed_product_bug"),
    ("after-fix-failure", "kane_02_after-fix-failure.stdout.txt", "negative_verified_oracle.json", "passed", "failed", 0, "success.complete"),
    ("after-fix-success", "kane_03_after-fix-success.stdout.txt", "positive_verified_oracle.json", "passed", "confirmed", 1, "success.complete"),
)
REQUIRED_GATES = {"build", "bug_reproduced", "repair", "negative_verified", "positive_verified", "astra_review"}
SOURCE_FILES = ("astra_verdict.json", "03_sol-repair.prompt.txt", "03_sol-repair.last.txt", "03_sol-repair.stderr.txt")

class EvidenceError(Exception):
    pass

def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_hash(path: Path) -> str:
    return sha(path.read_bytes())

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def git(root: Path, *cmd: str) -> bytes:
    r = subprocess.run(["git", "-C", str(root), *cmd], capture_output=True, timeout=15)
    if r.returncode:
        raise EvidenceError("git " + " ".join(cmd) + ": " + r.stderr.decode(errors="replace")[:200])
    return r.stdout

def parse_run(data: bytes) -> dict:
    ends = []
    for raw in data.decode("utf-8").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "run_end":
            ends.append(event)
    require(len(ends) == 1, "Kane evidence must include exactly one run_end event")
    return ends[0]

def flag(event: dict, name: str, expected: str) -> str:
    mem = event.get("context", {}).get("memory", {})
    require(name in mem, "Missing browser observation: " + name)
    val = str(mem[name].get("extracted_value", ""))
    require(val == expected, f"Unexpected {name}: {val!r} (expected {expected!r})")
    return val

def commit_info(root: Path) -> dict:
    defective = "1d39c57"
    repaired = "372fd4d"
    for c in (defective, repaired):
        require(git(root, "cat-file", "-t", c).strip() == b"commit", f"Missing commit {c}")
    git(root, "merge-base", "--is-ancestor", defective, repaired)
    git(root, "merge-base", "--is-ancestor", repaired, "HEAD")
    baseline_app = git(root, "show", defective + ":app.py")
    repaired_app = git(root, "show", repaired + ":app.py")
    current = (root / "app.py").read_bytes()
    require(current == repaired_app, "app.py differs from Kane-verified repair commit; reverify before claiming current behavior")
    require(b"BUILD defect" in baseline_app and b"showResult('Booking confirmed'" in baseline_app,
            "Baseline application no longer contains expected premature-confirmation code")
    require(b"await pollBooking(data);" in repaired_app and b"if (data.status === 'confirmed')" in repaired_app,
            "Repaired app lacks expected confirmation-status path")
    require(baseline_app != repaired_app, "No actual application repair between commits")
    return {"defective": git(root, "rev-parse", defective).decode().strip(),
            "repaired": git(root, "rev-parse", repaired).decode().strip(),
            "defective_app_sha256": sha(baseline_app),
            "repaired_app_sha256": sha(repaired_app)}

def capture(root: Path, private: Path) -> dict:
    commits = commit_info(root)
    state = read_json(private / "state.json")
    require(REQUIRED_GATES <= set(state.get("completed", [])), "Required gates absent from state")
    require(state.get("kane_runs") == 3 and state.get("model_calls") == 4,
            "Unexpected Kane/model usage for frozen November 17 run")
    verdict = read_json(private / "astra_verdict.json")
    require(verdict.get("verdict") == "PASS" and verdict.get("findings") == [],
            "Astra verdict not a clean PASS")
    prompt = (private / "03_sol-repair.prompt.txt").read_text(encoding="utf-8")
    require("bug_repro_oracle.json" in prompt and "kane_*_baseline-defect.stdout.txt" in prompt,
            "Sol repair prompt does not reference real Kane result and independent oracle")
    require("pending" in prompt.lower() and "confirmed" in prompt.lower(),
            "Sol repair request does not specify confirmation-state change")
    sol_trace = (private / "03_sol-repair.stderr.txt").read_text(encoding="utf-8")
    require("cat PROJECT_BRIEF.md && cat .kane_autopilot_private/bug_repro_oracle.json" in sol_trace,
            "Sol trace does not show reading the independent Kane+SQLite oracle")
    require("cat .kane_autopilot_private/kane_01_baseline-defect.stdout.txt" in sol_trace,
            "Sol trace does not show opening Kane's raw browser NDJSON")
    require('"type":"run_end"' in sol_trace,
            "Kane result text not present in Sol's recorded tool output")
    reply = (private / "03_sol-repair.last.txt").read_text(encoding="utf-8")
    require("pending" in reply.lower() and "poll" in reply.lower(), "No repair explanation in Sol output")
    source_sha = {name: file_hash(private / name) for name in SOURCE_FILES}
    run_rows = []
    consumed = 0.0
    for label, logfile, oraclefile, expected_kane, expected_worker, expected_count, expected_reason in RUNS:
        raw = (private / logfile).read_bytes()
        end = parse_run(raw)
        require(end.get("status") == expected_kane and end.get("reason_code") == expected_reason,
                f"Unexpected Kane result or error class for {label}")
        result_code = int(end.get("result_code", -1))
        require(result_code == (740 if label == "baseline-defect" else 100),
                f"Unexpected Kane result code in {label}")
        require(end.get("test_url", "").startswith("https://test-manager.lambdatest.com/"),
                "Missing actual Test Manager evidence reference")
        observed = {}
        if label == "after-fix-success":
            observed["success_visible"] = flag(end, "booking_confirmed_visible", "true")
            observed["booking_listed"] = flag(end, "kane_ok_2026_booking_listed", "true")
            observed["listed_confirmed"] = flag(end, "kane_ok_2026_booking_confirmed", "true")
        else:
            observed["success_visible"] = flag(end, "booking_confirmed_success_message_visible",
                                               "true" if label == "baseline-defect" else "false")
            observed["failure_visible"] = flag(end, "booking_not_confirmed_text_visible",
                                               "false" if label == "baseline-defect" else "true")
        oracle_bytes = (private / oraclefile).read_bytes()
        oracle = json.loads(oracle_bytes)
        require(oracle.get("kane") == end, f"Oracle Kane object differs from raw NDJSON: {label}")
        job = oracle.get("job", {})
        fixture = "KANE-OK-2026" if label == "after-fix-success" else "KANE-FAIL-2026"
        require(job.get("customer") == fixture and job.get("status") == expected_worker
                and job.get("accepted") is True and oracle.get("db_confirmed") == expected_count,
                f"Independent job/SQLite oracle mismatch: {label}")
        credit = end.get("credits_consumed")
        require(isinstance(credit, (int, float)) and 0 <= credit <= 400, "Invalid credit value")
        consumed += credit
        run_rows.append({"label": label, "kane_status": expected_kane,
                         "reason_code": expected_reason, "result_code": result_code,
                         "browser_observations": observed,
                         "worker_status": expected_worker,
                         "confirmed_rows": expected_count,
                         "fixture": fixture,
                         "kane_run_end_utc": end.get("ts"),
                         "kane_credits_reported": round(float(credit), 5),
                         "raw_ndjson_sha256": sha(raw),
                         "raw_oracle_sha256": sha(oracle_bytes)})
    require(abs(consumed - float(state["credits_observed"])) < 0.001,
            "Credits in run_end objects disagree with controller state")
    return {
        "schema_version": 1,
        "evidence_kind": "Derived summary of an actual local run; not a digital signature or complete Kane evidence pack",
        "limits": ["Raw authenticated Kane sessions are retained privately, not included here",
                   "Kane's baseline natural-language summary contains contradictory wording; structured browser observations are reported instead",
                   "Recorded evidence verifies the November 17 source commit, not arbitrary future edits",
                   "Commit IDs were rewritten for GitHub author-email privacy after the Kane run; original source trees and app SHA-256 were preserved"],
        "commits": commits,
        "controller": {"source": "Original autonomous controller v3; installed separately from Git during the run",
                       "sol_repair_prompt_sha256": source_sha["03_sol-repair.prompt.txt"],
                       "sol_repair_response_sha256": source_sha["03_sol-repair.last.txt"],
                       "feedback_inputs": ["bug_repro_oracle.json", "kane_01_baseline-defect.stdout.txt"],
                       "recorded_sol_file_reads": ["bug_repro_oracle.json", "kane_01_baseline-defect.stdout.txt"],
                       "sol_tool_trace_sha256": source_sha["03_sol-repair.stderr.txt"],
                       "feedback_output": "repair commit 372fd4d"},
        "runs": run_rows,
        "astra": {"verdict": "PASS", "blocking_findings": 0,
                  "raw_verdict_sha256": source_sha["astra_verdict.json"]},
        "accounting": {"model_calls": state["model_calls"], "kane_runs": state["kane_runs"],
                       "kane_credits_reported": round(consumed, 5)},
        "private_source_sha256": source_sha,
    }

def validate_public_receipt(receipt: dict, commits: dict) -> None:
    require(receipt.get("schema_version") == 1 and receipt.get("commits") == commits,
            "Receipt Git metadata/version mismatch")
    runs = receipt.get("runs")
    require(isinstance(runs, list) and len(runs) == len(RUNS), "Incorrect public run count")
    total = 0.
    for row, (label, _logfile, _oracle, kane_status, worker_status, db_rows, reason) in zip(runs, RUNS):
        require(row.get("label") == label and row.get("kane_status") == kane_status
                and row.get("worker_status") == worker_status
                and row.get("confirmed_rows") == db_rows
                and row.get("reason_code") == reason,
                f"Inconsistent receipt scenario: {label}")
        require(row.get("fixture") == ("KANE-OK-2026" if label == "after-fix-success" else "KANE-FAIL-2026"),
                "Fixture mismatch")
        expected = ({"success_visible": "true", "booking_listed": "true", "listed_confirmed": "true"}
                    if label == "after-fix-success" else
                    {"success_visible": "true", "failure_visible": "false"} if label == "baseline-defect" else
                    {"success_visible": "false", "failure_visible": "true"})
        require(row.get("browser_observations") == expected, f"Inconsistent browser flags for {label}")
        for key in ("raw_ndjson_sha256", "raw_oracle_sha256"):
            require(isinstance(row.get(key), str) and len(row[key]) == 64
                    and all(c in "0123456789abcdef" for c in row[key]), "Invalid SHA256 field")
        value = row.get("kane_credits_reported")
        require(isinstance(value, (int, float)) and 0 <= value <= 400, "Invalid credit accounting")
        total += value
    require(receipt.get("astra", {}).get("verdict") == "PASS"
            and receipt["astra"].get("blocking_findings") == 0, "Astra receipt mismatch")
    require(receipt.get("controller", {}).get("feedback_inputs") == [
        "bug_repro_oracle.json", "kane_01_baseline-defect.stdout.txt"]
        and receipt["controller"].get("recorded_sol_file_reads") == [
        "bug_repro_oracle.json", "kane_01_baseline-defect.stdout.txt"], "Missing recorded feedback input/read")
    require(receipt.get("accounting", {}).get("kane_runs") == 3
            and receipt["accounting"].get("model_calls") == 4
            and abs(total - receipt["accounting"].get("kane_credits_reported", -1)) < 0.0002,
            "Run totals don't agree")

def serialize(x: dict) -> bytes:
    return (json.dumps(x, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--private", action="store_true", help="Reconstruct receipt from original local private evidence")
    p.add_argument("--write", action="store_true", help="Write sanitized receipt (requires --private)")
    args = p.parse_args(argv)
    try:
        root = args.root.resolve()
        receipt = root / "evidence" / "closed_loop.json"
        if args.write and not args.private:
            raise EvidenceError("--write requires --private; will not synthesize a receipt")
        commits = commit_info(root)
        if args.private:
            rebuilt = capture(root, root / ".kane_autopilot_private")
            if args.write:
                receipt.parent.mkdir(parents=True, exist_ok=True)
                receipt.write_bytes(serialize(rebuilt))
            else:
                require(receipt.exists(), "Public receipt missing")
                require(receipt.read_bytes() == serialize(rebuilt), "Public receipt differs from private evidence")
            print("PASS: source NDJSON, agent handoff, SQLite oracles, Astra and Git verified")
        else:
            require(receipt.exists(), "Public receipt missing")
            r = read_json(receipt)
            validate_public_receipt(r, commits)
            print("PASS: public receipt matches Git-verified app/commits. PRIVATE KANE LOGS NOT RECHECKED.")
    except (EvidenceError, OSError, json.JSONDecodeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print("FAIL CLOSED: " + str(exc), file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
