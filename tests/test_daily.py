import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

import briefing
import daily


def berlin(value):
    return dt.datetime.fromisoformat(value).astimezone(daily.TZ)


class MemoryLedger:
    def __init__(self):
        self.records = {}

    def ensure_branch(self):
        pass

    def read(self, day):
        return copy.deepcopy(self.records.get(day))

    def write(self, day, record):
        self.records[day] = copy.deepcopy(record)


class OfflineTest(unittest.TestCase):
    def setUp(self):
        # Defense in depth, including libraries which bypass requests.
        for name in ("connect", "connect_ex"):
            p = patch.object(socket.socket, name, side_effect=AssertionError("Network forbidden in tests"))
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GITHUB_TOKEN": "",
                                   "SENDGRID_API_KEY": "fake", "MAIL_FROM": "from@example.invalid",
                                   "MAIL_TO": "to@example.invalid"}, clear=True)
        p.start()
        self.addCleanup(p.stop)


class SendTests(OfflineTest):
    def send_at(self, start, finish, response=None):
        response = response or Mock(status_code=202, headers={"X-Message-Id": "test-id"})
        with patch.object(briefing.requests, "post", return_value=response) as post:
            result = briefing.senden("html", "file", "text", {}, berlin(start),
                                      clock=lambda: berlin(finish))
        return post.call_args.kwargs["json"], result

    def test_dst_and_both_transition_days(self):
        for day, offset, utc_hour in [("2026-03-28", "+01:00", 6),
                                       ("2026-03-29", "+02:00", 5),
                                       ("2026-10-24", "+02:00", 5),
                                       ("2026-10-25", "+01:00", 6)]:
            with self.subTest(day=day):
                p, r = self.send_at(f"{day}T05:17:00{offset}", f"{day}T06:58:30{offset}")
                self.assertEqual(dt.datetime.fromtimestamp(p["send_at"], dt.timezone.utc).hour, utc_hour)
                self.assertEqual(r["late_seconds"], 0)
                self.assertEqual(p["custom_args"]["circumspectio_date"], day)

    def test_long_generation_does_not_submit_past_send_at(self):
        p, r = self.send_at("2026-10-18T06:17:00+02:00", "2026-10-18T10:56:00+02:00")
        self.assertNotIn("send_at", p)
        self.assertEqual(r["late_seconds"], 14160)
        self.assertEqual(r["message_id"], "test-id")

    def test_exact_target_and_short_buffer(self):
        for finish, scheduled in [("06:59:59", True), ("07:00:00", False)]:
            p, _ = self.send_at("2026-10-18T05:17:00+02:00", f"2026-10-18T{finish}+02:00")
            self.assertEqual("send_at" in p, scheduled)

    def test_crossing_midnight_never_sends_stale_issue(self):
        with patch.object(briefing.requests, "post") as post, self.assertRaises(RuntimeError):
            briefing.senden("h", "f", "t", {}, berlin("2026-10-18T06:00:00+02:00"),
                             clock=lambda: berlin("2026-10-19T00:01:00+02:00"))
        post.assert_not_called()

    def test_rejection_is_not_accepted(self):
        with self.assertRaises(RuntimeError):
            self.send_at("2026-10-18T05:17:00+02:00", "2026-10-18T06:00:00+02:00",
                         Mock(status_code=500))

    def test_ledger_latency_can_cross_deadline(self):
        moments = iter([berlin("2026-10-18T06:59:59+02:00"),
                        berlin("2026-10-18T07:00:05+02:00"),
                        berlin("2026-10-18T07:00:05+02:00")])
        with patch.object(briefing.requests, "post", return_value=Mock(status_code=202, headers={})) as post:
            result = briefing.senden("h", "f", "t", {}, berlin("2026-10-18T05:17:00+02:00"),
                                      clock=lambda: next(moments), before_send=Mock())
        self.assertNotIn("send_at", post.call_args.kwargs["json"])
        self.assertEqual(result["late_seconds"], 5)

    def test_slow_sendgrid_response_is_not_reported_on_time(self):
        moments = iter([berlin("2026-10-18T06:59:59+02:00"),
                        berlin("2026-10-18T07:00:10+02:00")])
        with patch.object(briefing.requests, "post", return_value=Mock(status_code=202, headers={})):
            result = briefing.senden("h", "f", "t", {}, berlin("2026-10-18T05:17:00+02:00"),
                                      clock=lambda: next(moments))
        self.assertEqual(result["late_seconds"], 10)
        self.assertIsNotNone(result["send_at"])
        ledger = MemoryLedger()
        ledger.records["2026-10-18"] = {**result, "status": "accepted"}
        with self.assertRaises(RuntimeError):
            daily.check(ledger, berlin("2026-10-18T07:05:00+02:00"))


class ExecutionTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.ledger = MemoryLedger()
        self.now = berlin("2026-10-18T05:17:00+02:00")
        self.generate = Mock(return_value="content")

    def send(self, content, started, now_fn, before_send):
        receipt = {"submitted_at": now_fn().isoformat(),
                   "accepted_at": now_fn().isoformat(),
                   "send_at": int(daily.target_for(started).timestamp()), "late_seconds": 0}
        before_send(receipt)
        return {**receipt, "http_status": 202, "message_id": "test"}

    def run_day(self, **kwargs):
        return daily.execute(self.ledger, self.generate, kwargs.pop("send", self.send),
                             now_fn=lambda: self.now, **kwargs)

    def test_duplicate_and_manual_rerun_cost_nothing(self):
        self.assertEqual(self.run_day()["status"], "accepted")
        self.assertEqual(self.run_day()["status"], "duplicate_suppressed")
        self.generate.assert_called_once()
        daily.check(self.ledger, self.now.replace(hour=7, minute=5))

    def test_second_trigger_is_useful_if_first_was_missing(self):
        self.now = self.now.replace(hour=6)
        self.assertEqual(self.run_day()["status"], "accepted")

    def test_windows_for_summer_winter_and_next_day(self):
        for timestamp, expected in [("2026-10-18T04:17:00+02:00", "outside_window"),
                                     ("2026-10-25T04:17:00+01:00", "outside_window"),
                                     ("2026-10-25T05:17:00+01:00", "accepted"),
                                     ("2026-10-26T00:17:00+01:00", "outside_window"),
                                     ("2026-10-26T12:01:00+01:00", "outside_window")]:
            with self.subTest(timestamp=timestamp):
                self.now = berlin(timestamp)
                self.assertEqual(self.run_day()["status"], expected)

    def test_new_day_has_separate_claim(self):
        self.run_day()
        self.now += dt.timedelta(days=1)
        self.run_day()
        self.assertEqual(self.generate.call_count, 2)

    def test_research_failure_requires_explicit_retry(self):
        self.generate.side_effect = ValueError("fake research failure")
        with self.assertRaises(ValueError):
            self.run_day()
        self.assertEqual(self.ledger.read("2026-10-18")["status"], "failed_before_send")
        with self.assertRaises(RuntimeError):
            self.run_day()
        self.generate.side_effect = None
        self.run_day(retry_failed=True)
        self.assertEqual(self.generate.call_count, 2)

    def test_timeout_after_post_is_unknown_and_blocks_retry(self):
        def uncertain(content, started, now_fn, before_send):
            before_send({})
            raise TimeoutError("response lost")
        with self.assertRaises(TimeoutError):
            self.run_day(send=uncertain)
        self.assertEqual(self.ledger.read("2026-10-18")["status"], "unknown")
        with self.assertRaises(RuntimeError):
            self.run_day(retry_failed=True)
        self.generate.assert_called_once()

    def test_interrupted_worker_stays_locked(self):
        for status in ("generating", "sending"):
            self.ledger.records["2026-10-18"] = {"status": status}
            with self.assertRaises(RuntimeError):
                self.run_day(retry_failed=True)
        self.generate.assert_not_called()

    def test_ledger_failure_prevents_costs(self):
        self.ledger.write = Mock(side_effect=RuntimeError("permission denied"))
        with self.assertRaises(RuntimeError):
            self.run_day()
        self.generate.assert_not_called()

    def test_intent_persistence_failure_prevents_send(self):
        writes = self.ledger.write
        def fail_sending(day, record):
            if record["status"] == "sending":
                raise RuntimeError("state service unavailable")
            writes(day, record)
        self.ledger.write = fail_sending
        with patch.object(briefing.requests, "post") as post, self.assertRaises(RuntimeError):
            self.generate.return_value = ("html", "file", "text", {})
            self.run_day(send=daily.send)
        post.assert_not_called()

    def test_accepted_record_write_failure_remains_unknown(self):
        writes = self.ledger.write
        def fail_accepted(day, record):
            if record["status"] == "accepted":
                raise RuntimeError("write failed after SendGrid accepted")
            writes(day, record)
        self.ledger.write = fail_accepted
        with self.assertRaises(RuntimeError):
            self.run_day()
        self.assertEqual(self.ledger.read("2026-10-18")["status"], "unknown")

    def test_deadline_check_missing_late_failed_and_unknown(self):
        with self.assertRaises(RuntimeError):
            daily.check(self.ledger, self.now)
        for record in [{"status": "unknown"}, {"status": "failed_before_send"},
                       {"status": "accepted", "submitted_at": "2026-10-18T10:56:00+02:00",
                        "accepted_at": "2026-10-18T10:56:01+02:00", "send_at": None}]:
            self.ledger.records["2026-10-18"] = record
            with self.assertRaises(RuntimeError):
                daily.check(self.ledger, self.now)


class LedgerTests(OfflineTest):
    def ledger(self, responses):
        session = Mock()
        session.request.side_effect = responses
        return daily.Ledger("owner/repo", "fake-token", session=session), session

    def test_atomic_create_conflict_blocks_competing_worker(self):
        ledger, session = self.ledger([Mock(status_code=404), Mock(status_code=409)])
        self.assertIsNone(ledger.read("2026-10-18"))
        with self.assertRaises(RuntimeError):
            ledger.write("2026-10-18", {"status": "generating"})
        self.assertNotIn("sha", session.request.call_args.kwargs["json"])

    def test_update_uses_read_sha_and_next_write_uses_new_sha(self):
        content = base64.b64encode(b'{"status":"generating"}').decode()
        ledger, session = self.ledger([
            Mock(status_code=200, json=lambda: {"sha": "old", "content": content}),
            Mock(status_code=200, json=lambda: {"content": {"sha": "new"}}),
            Mock(status_code=409)])
        ledger.read("2026-10-18")
        ledger.write("2026-10-18", {"status": "sending"})
        self.assertEqual(session.request.call_args.kwargs["json"]["sha"], "old")
        with self.assertRaises(RuntimeError):
            ledger.write("2026-10-18", {"status": "accepted"})
        self.assertEqual(session.request.call_args.kwargs["json"]["sha"], "new")

    def test_auth_or_network_failure_never_looks_like_absent_state(self):
        for response in [Mock(status_code=403), Mock(status_code=500)]:
            ledger, _ = self.ledger([response])
            with self.assertRaises(RuntimeError):
                ledger.read("2026-10-18")

    def test_branch_initialization_checks_race_result(self):
        ledger, _ = self.ledger([
            Mock(status_code=404),
            Mock(status_code=200, json=lambda: {"default_branch": "main"}),
            Mock(status_code=200, json=lambda: {"object": {"sha": "base"}}),
            Mock(status_code=422), Mock(status_code=200)])
        ledger.ensure_branch()


class LayoutTests(OfflineTest):
    def test_cli_fixture_offline_renders_without_any_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(briefing, "OUT", Path(directory)), \
                patch("sys.argv", ["briefing.py", "--aus-json", str(daily.ROOT / "beispiel.json"),
                                   "--dry-run", "--offline"]), \
                patch.object(briefing, "recherchieren", side_effect=AssertionError("Paid API forbidden")), \
                patch.object(briefing, "senden", side_effect=AssertionError("Real email forbidden")):
            briefing.main()
            self.assertIn("Circumspectio", (Path(directory) / "circumspectio.html").read_text())

    def test_legacy_entrypoint_cannot_bypass_daily_ledger(self):
        with patch("sys.argv", ["briefing.py"]), self.assertRaises(SystemExit):
            briefing.main()


if __name__ == "__main__":
    unittest.main()
