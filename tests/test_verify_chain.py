"""Adversarial tests of the public evidence checker, not a substitute for Kane."""
import importlib.util
import json
from pathlib import Path
import unittest

module_file = Path(__file__).resolve().parents[1] / 'tools' / 'verify_chain.py'
spec = importlib.util.spec_from_file_location('falsegreen_evidence_checker', module_file)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class EvidenceVerifierTests(unittest.TestCase):
    def test_parse_one_valid_run_end(self):
        got = mod.parse_run(b'{"type":"noise"}\n{"type":"run_end","status":"passed"}\n')
        self.assertEqual(got['status'], 'passed')

    def test_missing_terminal_event_is_not_pass(self):
        with self.assertRaises(mod.EvidenceError):
            mod.parse_run(b'{"type":"run_start"}\n')

    def test_two_terminal_events_are_rejected(self):
        with self.assertRaises(mod.EvidenceError):
            mod.parse_run(b'{"type":"run_end"}\n{"type":"run_end"}\n')

    def test_failed_assertion_flag_is_not_silently_accepted(self):
        with self.assertRaises(mod.EvidenceError):
            mod.flag({'context':{'memory':{'x':{'extracted_value':'false'}}}},'x','true')

    def test_missing_observation_is_rejected(self):
        with self.assertRaises(mod.EvidenceError):
            mod.flag({'context':{'memory':{}}},'x','true')

    def test_public_receipt_rejects_falsified_browser_result(self):
        root = Path(__file__).resolve().parents[1]
        commits = mod.commit_info(root)
        receipt = json.loads((root/'evidence'/'closed_loop.json').read_text())
        mod.validate_public_receipt(receipt, commits)
        receipt['runs'][0]['browser_observations']['success_visible'] = 'false'
        with self.assertRaises(mod.EvidenceError):
            mod.validate_public_receipt(receipt, commits)

    def test_receipt_rejects_inconsistent_credits(self):
        root = Path(__file__).resolve().parents[1]
        commits = mod.commit_info(root)
        receipt = json.loads((root/'evidence'/'closed_loop.json').read_text())
        receipt['accounting']['kane_credits_reported'] = 1000
        with self.assertRaises(mod.EvidenceError):
            mod.validate_public_receipt(receipt, commits)

    def test_receipt_rejects_wrong_git_commit(self):
        root = Path(__file__).resolve().parents[1]
        commits = mod.commit_info(root)
        receipt = json.loads((root/'evidence'/'closed_loop.json').read_text())
        receipt['commits']['repaired'] = '0' * 40
        with self.assertRaises(mod.EvidenceError):
            mod.validate_public_receipt(receipt, commits)

if __name__=='__main__':
    unittest.main()
