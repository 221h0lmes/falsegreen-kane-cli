#!/usr/bin/env python3
"""No-network, no-credit developer quality gate for False Green."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

BAD_TRACKED_PARTS = {'.kane_autopilot_private', '.testmuai', '__pycache__', '.venv'}
BAD_TRACKED_SUFFIXES = ('.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.pyc', '.evidence')

def step(cmd: list[str], cwd: Path) -> bool:
    print('$ ' + ' '.join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    return r.returncode == 0

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args(argv)
    root = args.root.resolve()
    if not (root/'app.py').is_file() or not (root/'.git').is_dir():
        print('ERROR: Expected False Green Git repository', file=sys.stderr)
        return 2
    result = subprocess.run(['git','ls-files','-z'], cwd=root, capture_output=True)
    if result.returncode:
        return 2
    tracked = [v.decode('utf-8',errors='replace') for v in result.stdout.split(b'\x00') if v]
    sensitive = [n for n in tracked if BAD_TRACKED_PARTS.intersection(Path(n).parts)
                 or n.endswith(BAD_TRACKED_SUFFIXES) or Path(n).name.startswith('.env')
                 or 'PRIVATE' in Path(n).name]
    if sensitive:
        print('FAIL: suspicious tracked paths: ' + ', '.join(sensitive), file=sys.stderr)
        return 2
    checks = [
        ['git','diff','--check'],
        [sys.executable,'-m','py_compile','app.py','tools/verify_chain.py','tools/quality_gate.py'],
        [sys.executable,'-m','unittest','discover','-s','tests','-v'],
        [sys.executable,'tools/verify_chain.py'],
    ]
    if (root/'.kane_autopilot_private'/'state.json').exists():
        checks.append([sys.executable,'tools/verify_chain.py','--private'])
    all_pass = True
    for cmd in checks:
        ok = step(cmd, root)
        print('PASS' if ok else 'FAIL', ':', cmd[0], cmd[1:], flush=True)
        all_pass = all_pass and ok
    if all_pass:
        print('QUALITY GATE PASS: local tests, provenance and tracked-file safety checks; no Kane browser run')
        return 0
    print('QUALITY GATE FAILED; no claim of runtime Kane verification from this command', file=sys.stderr)
    return 2

if __name__ == '__main__':
    raise SystemExit(main())
