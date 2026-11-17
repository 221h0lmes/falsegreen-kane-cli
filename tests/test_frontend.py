"""Execute the shipped UI script, without claiming real-browser verification.

Node's built-in VM is an optional test tool, not an application dependency.
"""

from pathlib import Path
import shutil
import subprocess
import unittest

from app import HTML


@unittest.skipUnless(shutil.which("node"), "UI script tests require optional Node.js")
class FrontendTests(unittest.TestCase):
    def run_scenario(self, scenario):
        script = HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("frontend_contract.js")), scenario],
            input=script, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + scenario, result.stdout)

    def test_pending_until_confirmed_status_and_listing(self):
        self.run_scenario("success")

    def test_worker_failure_never_displays_confirmation(self):
        self.run_scenario("failure")

    def test_transient_status_error_recovers(self):
        self.run_scenario("transient-error")

    def test_repeated_status_errors_offer_recheck_of_same_job(self):
        self.run_scenario("retry")

    def test_poll_timeout_keeps_pending(self):
        self.run_scenario("timeout")

    def test_unrelated_confirmed_job_cannot_confirm_request(self):
        self.run_scenario("wrong-job")

    def test_missing_status_after_restart_is_uncertain(self):
        self.run_scenario("missing-job")

    def test_lost_submission_response_is_uncertain(self):
        self.run_scenario("submission-network-error")

    def test_rejected_submission_displays_not_confirmed(self):
        self.run_scenario("submission-rejected")

    def test_unexpected_post_success_cannot_confirm_request(self):
        self.run_scenario("unexpected-acceptance")
