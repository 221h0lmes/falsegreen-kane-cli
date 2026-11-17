"""Real worker / SQLite / HTTP checks. These do not claim browser verification."""

import http.client
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from app import BookingService, Handler, LocalServer


def booking(customer="KANE-OK-2026"):
    return {"customer": customer, "date": "2026-11-19", "time": "19:00", "party_size": 2}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bookings.sqlite3"
        self.service = BookingService(self.path, worker_delay=0.03)

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def settle(self, job_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.service.status(job_id)
            if state and state["status"] != "pending":
                return state
            time.sleep(0.005)
        self.fail("Worker did not reach a terminal state within three seconds")

    def rows(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT customer, status FROM bookings ORDER BY customer").fetchall()

    def test_success_is_committed_and_survives_restart(self):
        job = self.service.accept(booking())
        self.assertEqual(job["status"], "pending")
        self.assertEqual(self.settle(job["id"])["status"], "confirmed")
        self.assertEqual(self.rows(), [("KANE-OK-2026", "confirmed")])
        self.service.close()
        self.service = BookingService(self.path, worker_delay=0.01)
        self.assertEqual(self.service.status(job["id"])["status"], "confirmed")
        self.assertEqual(self.service.bookings()[0]["customer"], "KANE-OK-2026")

    def test_acceptance_precedes_persistence(self):
        # Hold the worker's commit lock to inspect acceptance without timing luck.
        with self.service.lock:
            job = self.service.accept(booking())
            self.assertEqual(self.service.status(job["id"])["status"], "pending")
            self.assertEqual(self.rows(), [])
        self.assertEqual(self.settle(job["id"])["status"], "confirmed")

    def test_fault_drops_exactly_one_accepted_job_before_persistence(self):
        self.service.arm_failure()
        failed = self.service.accept(booking("KANE-FAIL-2026"))
        normal = self.service.accept(booking())
        self.assertEqual(failed["status"], "pending")
        self.assertEqual(self.settle(failed["id"])["status"], "failed")
        self.assertEqual(self.settle(normal["id"])["status"], "confirmed")
        self.assertEqual(self.rows(), [("KANE-OK-2026", "confirmed")])
        self.assertEqual(len(self.service.bookings()), 1)

    def test_invalid_submission_does_not_consume_fault(self):
        self.service.arm_failure()
        with self.assertRaises(ValueError):
            self.service.accept(booking(""))
        job = self.service.accept(booking("KANE-FAIL-2026"))
        self.assertEqual(self.settle(job["id"])["status"], "failed")
        self.assertEqual(self.rows(), [])

    def test_reset_invalidates_inflight_and_queued_jobs_and_disarms_fault(self):
        self.service.worker_delay = 0.08
        old = [self.service.accept(booking("old")) for _ in range(3)]
        # Queue acceptance has completed; reset must also cover a sleeping worker.
        self.service.arm_failure()
        self.service.reset()
        fresh = self.service.accept(booking())
        self.assertEqual(self.settle(fresh["id"])["status"], "confirmed")
        for job in old:
            self.assertIsNone(self.service.status(job["id"]))
        self.assertEqual(self.rows(), [("KANE-OK-2026", "confirmed")])
        self.service.reset()
        self.assertEqual(self.rows(), [])

    def test_storage_error_is_failed_and_worker_continues(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TRIGGER reject_booking BEFORE INSERT ON bookings
                BEGIN SELECT RAISE(ABORT, 'simulated storage rejection'); END""")
        job = self.service.accept(booking("Storage failure"))
        self.assertEqual(self.settle(job["id"])["status"], "failed")
        self.assertEqual(self.rows(), [])
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER reject_booking")
        normal = self.service.accept(booking())
        self.assertEqual(self.settle(normal["id"])["status"], "confirmed")

    def test_validation_rejects_bad_fields(self):
        invalid = [None, [], {}, booking("  "), booking("x" * 101), booking("a\nb"), booking("\ud800")]
        for field, values in {"date": ["2026-02-30", "26-11-19", None, 42],
                              "time": ["25:00", "7:00", "19:00:01", None],
                              "party_size": [0, 13, 2.5, "2", True, None]}.items():
            invalid.extend(dict(booking(), **{field: value}) for value in values)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.service.accept(data)
        self.assertEqual(self.rows(), [])

    def test_concurrent_acceptance_consumes_fault_once(self):
        self.service.arm_failure()
        jobs = []
        result_lock = threading.Lock()

        def submit(index):
            job = self.service.accept(booking(f"Concurrent {index}"))
            with result_lock:
                jobs.append(job)

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        states = [self.settle(job["id"])["status"] for job in jobs]
        self.assertEqual(states.count("failed"), 1)
        self.assertEqual(states.count("confirmed"), 5)
        self.assertEqual(len(self.rows()), 5)


class MemorySocket:
    """Byte transport for the real HTTP parser when the sandbox denies sockets."""

    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, mode, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, seconds):
        pass


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class HandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / "http.sqlite3"
        cls.service = BookingService(cls.path, worker_delay=0.08)
        cls.server = SimpleNamespace(service=cls.service, qa_token="test-qa-token", server_port=8765)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()
        cls.temp.cleanup()

    def setUp(self):
        self.service.reset()

    def request(self, method, path, data=None, headers=None, raw=None):
        request_headers = dict(headers or {})
        body = raw
        if data is not None:
            body = json.dumps(data)
            request_headers.setdefault("Content-Type", "application/json")
        encoded = (body or "").encode()
        request_headers.setdefault("Host", f"127.0.0.1:{self.server.server_port}")
        request_headers.setdefault("Content-Length", str(len(encoded)))
        head = f"{method} {path} HTTP/1.0\r\n" + "".join(f"{key}: {value}\r\n" for key, value in request_headers.items()) + "\r\n"
        transport = MemorySocket(head.encode() + encoded)
        QuietHandler(transport, ("127.0.0.1", 12345), self.server)
        response = http.client.HTTPResponse(MemorySocket(bytes(transport.output)))
        response.begin()
        content = response.read()
        payload = json.loads(content) if "application/json" in response.getheader("Content-Type", "") else content.decode()
        return response.status, payload, dict(response.getheaders())

    def settle(self, path):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            code, job, _ = self.request("GET", path)
            self.assertEqual(code, 200)
            if job["status"] != "pending":
                return job
            time.sleep(0.01)
        self.fail("HTTP status never reached terminal state")

    def test_health_and_page(self):
        code, data, _ = self.request("GET", "/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(data, {"app": "falsegreen", "ok": True, "simulation": True, "instance_id": ""})
        code, html, headers = self.request("GET", "/")
        self.assertEqual(code, 200)
        for label in ("Customer name", "Date", "Time", "Party size", "My Bookings", "Booking confirmed", "Booking not confirmed"):
            self.assertIn(label, html)
        self.assertNotIn("test-qa-token", html)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_202_is_pending_and_failure_is_absent_from_sqlite(self):
        code, _, _ = self.request("POST", "/qa/fail-next", headers={"X-QA-Token": "test-qa-token"})
        self.assertEqual(code, 200)
        code, accepted, _ = self.request("POST", "/api/bookings", booking("KANE-FAIL-2026"))
        self.assertEqual(code, 202)
        self.assertEqual(accepted["status"], "pending")
        failed = self.settle(accepted["status_url"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("error", failed)
        self.assertEqual(self.request("GET", "/api/bookings")[1]["bookings"], [])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM bookings WHERE customer = ? AND status = 'confirmed'", ("KANE-FAIL-2026",)).fetchone()[0], 0)
        code, accepted, _ = self.request("POST", "/api/bookings", booking())
        self.assertEqual(code, 202)
        self.assertEqual(self.settle(accepted["status_url"])["status"], "confirmed")
        self.assertEqual(self.request("GET", "/api/bookings")[1]["bookings"][0]["customer"], "KANE-OK-2026")

    def test_qa_requires_token_and_rejected_request_does_not_arm_fault(self):
        for path in ("/qa/reset", "/qa/fail-next"):
            for headers in ({}, {"X-QA-Token": "wrong"}):
                self.assertEqual(self.request("POST", path, headers=headers)[0], 401)
        _, accepted, _ = self.request("POST", "/api/bookings", booking())
        self.assertEqual(self.settle(accepted["status_url"])["status"], "confirmed")
        self.assertEqual(self.request("POST", "/qa/reset", headers={"X-QA-Token": "test-qa-token"})[0], 200)
        self.assertEqual(self.request("GET", "/api/bookings")[1]["bookings"], [])

    def test_local_host_and_origin_enforced(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"Host": "localhost:123"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", "/healthz", headers=headers)[0], 403)
                self.assertEqual(self.request("POST", "/api/bookings", booking(), headers=headers)[0], 403)
        headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}"}
        self.assertEqual(self.request("POST", "/api/bookings", booking(), headers=headers)[0], 202)

    def test_invalid_requests_and_unknown_status(self):
        self.assertEqual(self.request("GET", "/api/bookings/missing")[0], 404)
        self.assertEqual(self.request("GET", "/qa/reset")[0], 404)
        self.assertEqual(self.request("POST", "/missing")[0], 404)
        self.assertEqual(self.request("POST", "/api/bookings", raw="{}")[0], 415)
        for raw in ('{"', '[]', '{}', '{"customer":"x"}', 'x' * 8193):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(self.request("POST", "/api/bookings", raw=raw,
                                              headers={"Content-Type": "application/json"})[0], 400)

    def test_cannot_bind_public_interface_or_use_empty_token(self):
        with self.assertRaises(ValueError):
            LocalServer(("0.0.0.0", 0), self.service, "token")
        with self.assertRaises(ValueError):
            LocalServer(("127.0.0.1", 0), self.service, "")


class HTTPTests(HandlerTests):
    """Run the same contract through real loopback sockets when permitted."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / "http.sqlite3"
        cls.service = BookingService(cls.path, worker_delay=0.08)
        try:
            cls.server = LocalServer(("127.0.0.1", 0), cls.service, "test-qa-token")
        except PermissionError as error:
            cls.service.close()
            cls.temp.cleanup()
            raise unittest.SkipTest(f"Environment forbids loopback sockets: {error}") from error
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.service.close()
        cls.temp.cleanup()

    def request(self, method, path, data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = dict(headers or {})
        body = raw
        if data is not None:
            body = json.dumps(data)
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            payload = json.loads(content) if "application/json" in response.getheader("Content-Type", "") else content.decode()
            return response.status, payload, dict(response.getheaders())
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
