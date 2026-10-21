"""Offline safety checks for the owned mail probe; no service is contacted."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import notification_delivery_probe as probe


class MailProbeTests(unittest.TestCase):
    def setUp(self):
        self.socket_guard = patch.object(socket, "create_connection", side_effect=AssertionError("offline test network blocked"))
        self.socket_guard.start()
        self.addCleanup(self.socket_guard.stop)
        self.connect_guard = patch.object(socket.socket, "connect", side_effect=AssertionError("offline test network blocked"))
        self.connect_guard.start()
        self.addCleanup(self.connect_guard.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix="owned-mail-probe-test-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.values = {"SMTP_HOST": "smtp.example.invalid", "SMTP_PORT": "587", "SMTP_USE_TLS": "true",
                       "SMTP_FROM": "Owned Check <sender@example.invalid>", "SMTP_USERNAME": "owned-user",
                       "SMTP_PASSWORD": "owned-private-password", "DELIVERY_TEST_RECIPIENT": "owned@example.invalid"}
        self.run_id = "a" * 32
        self.recipient_hash = probe.digest(self.values["DELIVERY_TEST_RECIPIENT"])
        self.send_args = dict(run_id=self.run_id, destination=self.folder, confirmed=True,
                              expected_recipient_sha256=self.recipient_hash, mailbox_deadline=1)

    def accepted(self, operation, request, timeout):
        self.assertEqual(operation, "smtp")
        self.assertTrue((self.folder / (self.run_id + ".attempt.json")).is_file())
        return {"smtp_accepted": True, "source_sha256": request["attempt"]["source_sha256"]}

    def write_env(self, values=None):
        target = self.folder / "private.env"
        target.write_text("\n".join(key + "=" + value for key, value in (values or self.values).items()), encoding="utf-8")
        return target

    def captured_attempt(self):
        with patch.object(probe, "run_child", side_effect=self.accepted):
            probe.send_owned(self.values, **self.send_args)
        return json.loads((self.folder / (self.run_id + ".attempt.json")).read_text())

    def test_default_inspection_never_sends_or_claims_delivery(self):
        with patch.object(probe, "run_child") as child, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(["--env-file", str(self.write_env())]), 0)
        child.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertTrue(result["smtp_inputs_ready"])
        self.assertFalse(result["network_attempted"])
        self.assertFalse(result["full_delivery_passed"])
        self.assertEqual(result["recipient_sha256"], self.recipient_hash)
        for secret in (self.values["SMTP_PASSWORD"], self.values["SMTP_USERNAME"], self.values["DELIVERY_TEST_RECIPIENT"]):
            self.assertNotIn(secret, output.getvalue())

    def test_missing_file_is_clean_and_network_free(self):
        with patch.object(probe, "run_child") as child, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(["--env-file", str(self.folder / "missing")]), 1)
        child.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["gate"], "private_input_missing_or_oversized")

    def test_missing_explicit_gate_creates_no_attempt_and_no_network(self):
        for changes in ({"confirmed": False}, {"run_id": "invalid"}, {"expected_recipient_sha256": "b" * 64},
                        {"mailbox_deadline": 0}, {"mailbox_deadline": 61}):
            with self.subTest(changes=changes), patch.object(probe, "run_child") as child:
                with self.assertRaises(probe.ProbeError):
                    probe.send_owned(self.values, **{**self.send_args, **changes})
                child.assert_not_called()
        self.assertEqual(list(self.folder.glob("*.attempt.json")), [])

    def test_invalid_configuration_never_reserves_or_sends(self):
        for changes in ({"SMTP_HOST": ""}, {"DELIVERY_TEST_RECIPIENT": ""},
                        {"SMTP_USE_TLS": "false"}, {"SMTP_PASSWORD": ""},
                        {"SMTP_PORT": "0"}, {"SMTP_USE_TLS": "maybe"},
                        {"DELIVERY_TEST_RECIPIENT": "one@example.invalid,two@example.invalid"},
                        {"SMTP_FROM": "owned@example.invalid\r\nBcc: stranger@example.invalid"}):
            with self.subTest(changes=changes), patch.object(probe, "run_child") as child:
                with self.assertRaises(probe.ProbeError):
                    probe.send_owned({**self.values, **changes}, **self.send_args)
                child.assert_not_called()
        self.assertEqual(list(self.folder.glob("*.attempt.json")), [])

    def test_implicit_tls_does_not_require_starttls(self):
        result = probe.smtp_configuration({**self.values, "SMTP_PORT": "465", "SMTP_USE_TLS": "false"})
        self.assertEqual(result["smtp_port"], 465)

    def test_duplicate_or_unknown_attempt_never_retries(self):
        path = self.folder / (self.run_id + ".attempt.json")
        probe.write_exclusive(path, {"smtp_outcome": "unknown"})
        before = path.read_bytes()
        with patch.object(probe, "run_child") as child, self.assertRaisesRegex(probe.ProbeError, "never_resend"):
            probe.send_owned(self.values, **self.send_args)
        child.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_marker_exists_before_send_and_no_imap_is_not_full_pass(self):
        with patch.object(probe, "run_child", side_effect=self.accepted) as child:
            result = probe.send_owned(self.values, **self.send_args)
        self.assertEqual(child.call_count, 1)
        self.assertTrue(result["smtp_accepted"])
        self.assertFalse(result["mailbox_received"])
        self.assertFalse(result["full_delivery_passed"])
        self.assertEqual(result["mailbox"]["mailbox_status"], "pending_configuration")
        self.assertNotIn(self.values["DELIVERY_TEST_RECIPIENT"], json.dumps(result))

    def test_post_acceptance_imap_failure_keeps_accepted_and_blocks_resend(self):
        with patch.object(probe, "run_child", side_effect=self.accepted) as child, \
                patch.object(probe, "check_mailbox", side_effect=TimeoutError("private service detail")):
            result = probe.send_owned(self.values, **self.send_args)
            with self.assertRaises(probe.ProbeError):
                probe.send_owned(self.values, **self.send_args)
        self.assertEqual(child.call_count, 1)
        self.assertTrue(result["smtp_accepted"])
        self.assertFalse(result["full_delivery_passed"])
        self.assertNotIn("private service detail", json.dumps(result))
        recorded = json.loads((self.folder / (self.run_id + ".smtp.json")).read_text())
        self.assertTrue(recorded["smtp_accepted"])

    def test_timeout_is_unknown_and_stays_reserved(self):
        with patch.object(probe, "run_child", return_value={"operation_failed": True, "error_type": "TimeoutExpired"}) as child:
            result = probe.send_owned(self.values, **self.send_args)
            with self.assertRaises(probe.ProbeError):
                probe.send_owned(self.values, **self.send_args)
        self.assertEqual(child.call_count, 1)
        self.assertFalse(result["smtp_accepted"])
        self.assertEqual(result["smtp_outcome"], "failed_or_unknown")

    def test_swapped_smtp_receipt_cannot_accept_an_unknown_attempt(self):
        with patch.object(probe, "run_child", return_value={"error_type": "TimeoutExpired"}):
            self.assertFalse(probe.send_owned(self.values, **self.send_args)["smtp_accepted"])
        other_run = "b" * 32
        with patch.object(probe, "run_child", side_effect=self.accepted):
            self.assertTrue(probe.send_owned(self.values, **{**self.send_args, "run_id": other_run})["smtp_accepted"])
        (self.folder / (self.run_id + ".smtp.json")).write_bytes((self.folder / (other_run + ".smtp.json")).read_bytes())
        with patch.object(probe, "check_mailbox", return_value={"mailbox_received": True}) as mailbox, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = probe.main(["mailbox", "--env-file", str(self.write_env()), "--receipt-dir", str(self.folder),
                               "--run-id", self.run_id])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue())["full_delivery_passed"])
        mailbox.assert_not_called()

    def test_each_smtp_binding_field_is_checked_before_mailbox_network(self):
        with patch.object(probe, "run_child", side_effect=self.accepted):
            probe.send_owned(self.values, **self.send_args)
        path = self.folder / (self.run_id + ".smtp.json")
        original = json.loads(path.read_text())
        for key, value in (("run_id", "b" * 32), ("message_id", "<other@nerkhbaan.invalid>"),
                           ("recipient_sha256", "b" * 64), ("source_sha256", "b" * 64)):
            with self.subTest(key=key):
                path.write_text(json.dumps({**original, key: value}))
                with patch.object(probe, "check_mailbox", return_value={"mailbox_received": True}) as mailbox, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    code = probe.main(["mailbox", "--env-file", str(self.write_env()), "--receipt-dir", str(self.folder),
                                       "--run-id", self.run_id])
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(output.getvalue())["full_delivery_passed"])
                mailbox.assert_not_called()

    def test_file_message_id_cannot_inject_an_imap_command(self):
        attempt = self.captured_attempt()
        attempt["message_id"] += '"\r\nX STORE 1 +FLAGS (\\Seen)'
        client = Mock()
        client.select.return_value = ("NO", [])
        request = {"imap": {"host": "imap.example.invalid", "port": 993, "username": "owned", "password": "private"},
                   "attempt": attempt, "deadline_seconds": 1}
        with patch.object(probe.imaplib, "IMAP4_SSL", return_value=client) as transport:
            with self.assertRaisesRegex(probe.ProbeError, "attempt_receipt_invalid"):
                probe.imap_child(request)
        transport.assert_not_called()

    def test_malformed_attempt_shapes_are_rejected_before_imap_connection(self):
        attempt = self.captured_attempt()
        invalid = [[], {}, {**attempt, "schema": True}, {**attempt, "run_id": 12},
                   {**attempt, "recipient_sha256": "not-a-hash"}, {**attempt, "source_sha256": "G" * 64},
                   {**attempt, "reserved_at_utc": "2026-10-19T10:00:00"},
                   {**attempt, "message_date": "Mon, 19 Oct 2026 10:00:00 +0000\r\nOther: value"}]
        for index, value in enumerate(invalid):
            with self.subTest(index=index), patch.object(probe.imaplib, "IMAP4_SSL") as transport:
                with self.assertRaisesRegex(probe.ProbeError, "attempt_receipt_invalid"):
                    probe.imap_child({"imap": {}, "attempt": value, "deadline_seconds": 1})
                transport.assert_not_called()

    def test_bound_mailbox_recheck_can_pass_without_resending(self):
        attempt = self.captured_attempt()
        values = {**self.values, "DELIVERY_IMAP_HOST": "imap.example.invalid", "DELIVERY_IMAP_PORT": "993",
                  "DELIVERY_IMAP_USERNAME": "owned", "DELIVERY_IMAP_PASSWORD": "private-imap-password"}
        with patch.object(probe, "run_child", return_value={"mailbox_received": True}) as child, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = probe.main(["mailbox", "--env-file", str(self.write_env(values)), "--receipt-dir", str(self.folder),
                               "--run-id", self.run_id])
        self.assertEqual(code, 0)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(child.call_args.args[0], "imap")
        result = json.loads(output.getvalue())
        self.assertTrue(result["full_delivery_passed"])
        for key in ("run_id", "message_id", "recipient_sha256", "source_sha256"):
            self.assertEqual(result[key], attempt[key])
        self.assertNotIn(values["DELIVERY_IMAP_PASSWORD"], output.getvalue())

    def test_private_env_does_not_interpolate_or_export_other_keys(self):
        path = self.write_env({**self.values, "SMTP_PASSWORD": "literal-${UNRELATED_SECRET}", "EGRESS_SSH_KEY_PATH": "private-key-path"})
        before = dict(os.environ)
        result = probe.load_private_settings(path)
        self.assertEqual(result["SMTP_PASSWORD"], "literal-${UNRELATED_SECRET}")
        self.assertNotIn("EGRESS_SSH_KEY_PATH", result)
        self.assertEqual(dict(os.environ), before)
        path.write_text(path.read_text() + "\nSMTP_HOST=duplicate.invalid\n")
        with self.assertRaisesRegex(probe.ProbeError, "duplicate"):
            probe.load_private_settings(path)

    def test_message_is_unique_and_has_only_owned_check_text(self):
        config = probe.smtp_configuration(self.values)
        attempt = {"run_id": self.run_id, "message_id": "<owned-test@nerkhbaan.invalid>", "message_date": "Mon, 19 Oct 2026 10:00:00 +0000"}
        message = probe.make_message(config, attempt)
        self.assertEqual(message["Message-ID"], attempt["message_id"])
        self.assertEqual(message["Date"], attempt["message_date"])
        self.assertEqual(message["X-Nerkhbaan-Delivery-Run"], self.run_id)
        self.assertEqual(message["To"], self.values["DELIVERY_TEST_RECIPIENT"])
        self.assertEqual(message.get_all("To"), [self.values["DELIVERY_TEST_RECIPIENT"]])
        self.assertNotIn("Bcc", message)
        self.assertEqual(message.get_content(), "Owned delivery check.\nRun: " + self.run_id + "\nNo reply is needed.\n")

    def test_imap_only_searches_owned_headers_and_fetches_peek_readonly(self):
        attempt = self.captured_attempt()
        headers = ("Message-ID: " + attempt["message_id"] + "\r\nX-Nerkhbaan-Delivery-Run: " + self.run_id + "\r\n\r\n").encode()
        client = Mock()
        client.select.return_value = ("OK", [b"1"])
        client.uid.side_effect = [("OK", [b"47"]), ("OK", [(b"47 header", headers), b")"])]
        request = {"imap": {"host": "imap.example.invalid", "port": 993, "username": "owned", "password": "private"},
                   "attempt": attempt, "deadline_seconds": 1}
        with patch.object(probe.imaplib, "IMAP4_SSL", return_value=client) as transport:
            result = probe.imap_child(request)
        tls = transport.call_args.kwargs["ssl_context"]
        self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(tls.check_hostname)
        client.select.assert_called_once_with("INBOX", readonly=True)
        self.assertEqual(client.uid.call_args_list[0].args,
                         ("search", None, "HEADER", "Message-ID", '"' + attempt["message_id"] + '"',
                          "HEADER", "X-Nerkhbaan-Delivery-Run", '"' + self.run_id + '"'))
        self.assertEqual(client.uid.call_args_list[1].args,
                         ("fetch", b"47", "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE X-NERKHBAAN-DELIVERY-RUN)])"))
        client.close.assert_not_called()
        self.assertTrue(result["mailbox_received"])
        self.assertFalse(result["message_marked_read"])

    def test_imap_search_substring_is_not_enough_for_acceptance(self):
        attempt = self.captured_attempt()
        client = Mock()
        client.select.return_value = ("OK", [])
        client.uid.side_effect = [("OK", [b"47"]), ("OK", [(b"47", b"Message-ID: <different@nerkhbaan.invalid>\r\n\r\n")])]
        request = {"imap": {"host": "imap.example.invalid", "port": 993, "username": "owned", "password": "private"},
                   "attempt": attempt, "deadline_seconds": 1}
        with patch.object(probe.imaplib, "IMAP4_SSL", return_value=client), self.assertRaises(probe.ProbeError):
            probe.imap_child(request)
        client.logout.assert_called_once()

    def test_child_uses_ephemeral_environment_and_timeout_without_parent_mutation(self):
        before = dict(os.environ)
        with patch.object(probe.subprocess, "run", return_value=Mock(returncode=0, stdout='{"smtp_accepted":true}')) as child:
            result = probe.run_child("smtp", {"private": "pipe-only"}, 45)
        self.assertTrue(result["smtp_accepted"])
        kwargs = child.call_args.kwargs
        self.assertGreaterEqual(len(kwargs["env"]["JWT_SECRET_KEY"]), 32)
        self.assertEqual(kwargs["timeout"], 45)
        self.assertNotIn("pipe-only", " ".join(child.call_args.args[0]))
        self.assertNotIn("SMTP_PASSWORD", kwargs["env"])
        self.assertEqual(dict(os.environ), before)
        with patch.object(probe.subprocess, "run", side_effect=subprocess.TimeoutExpired("owned", 45)):
            self.assertTrue(probe.run_child("smtp", {}, 45)["outcome_unknown"])

    def test_real_candidate_helper_is_used_in_isolated_offline_child(self):
        code = r'''
import json, socket, sys
from unittest.mock import Mock, patch
sys.path.insert(0, sys.argv[1])
import notification_delivery_probe as p
request = json.load(sys.stdin)
with patch.object(socket, 'create_connection', side_effect=AssertionError('network blocked')), \
     patch.object(socket.socket, 'connect', side_effect=AssertionError('network blocked')):
    sys.path.insert(0, str(p.ROOT / 'apps' / 'api'))
    from app import security
    client = Mock()
    with patch.object(security.smtplib, 'SMTP', return_value=client) as transport:
        outcome = p.smtp_child(request)
    sent = client.send_message.call_args.args[0]
    print(json.dumps({'accepted': outcome['smtp_accepted'], 'sends': client.send_message.call_count,
        'helper_module': security.send_smtp_message.__module__, 'db_imported': 'app.db' in sys.modules,
        'tls': client.starttls.call_count, 'recipient_matched': str(sent['To']) == request['smtp']['recipient'],
        'source_matched': outcome['source_sha256'] == request['attempt']['source_sha256']}))
'''
        request = {"smtp": probe.smtp_configuration(self.values), "attempt": self.captured_attempt()}
        before = dict(os.environ)
        child_env = {key: value for key, value in os.environ.items()
                     if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "SYSTEMDRIVE"}}
        child_env["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(Path(probe.__file__).parent)],
            input=json.dumps(request), text=True, capture_output=True, timeout=20, cwd=self.folder, env=child_env)
        self.assertEqual(result.returncode, 0, "isolated helper fixture failed")
        summary = json.loads(result.stdout)
        self.assertEqual(summary, {"accepted": True, "sends": 1, "helper_module": "app.security", "db_imported": False,
                                  "tls": 1, "recipient_matched": True, "source_matched": True})
        self.assertEqual(dict(os.environ), before)


if __name__ == "__main__":
    unittest.main()
