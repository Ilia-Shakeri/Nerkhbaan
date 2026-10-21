from __future__ import annotations

import hashlib
import json
import os
import unittest
from urllib.parse import parse_qs
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")

from app.services import communication_transport as t


class CommunicationTransportTests(unittest.TestCase):
    def setUp(self):
        self.provider = {"enabled": True, "provider_id": "kavenegar", "config": {"sender": "1000123"}}
        self.secret = {"api_key": "ownedfixturekey0123456789"}
        self.phone = "+989120000000"
        for name, target in (("connection", "socket.create_connection"), ("lookup", "socket.getaddrinfo")):
            guard = patch(target, side_effect=AssertionError("real_network_forbidden"))
            setattr(self, name, guard.start())
            self.addCleanup(guard.stop)

    def send(self, **changes):
        return t.send_transport(changes.pop("channel", "sms"), changes.pop("provider", self.provider),
                                changes.pop("secret", self.secret), phone=self.phone, message="Owned alert",
                                delivery_key="owned-key", **changes)

    def test_disabled_and_bad_configuration_do_not_resolve(self):
        for provider in ({**self.provider, "enabled": False}, {**self.provider, "provider_id": "sms_http"},
                         {**self.provider, "config": {"endpoint": "https://example.invalid"}}):
            self.assertEqual(self.send(provider=provider).status, "failed")
        self.lookup.assert_not_called()

    def test_fixed_official_sms_post_and_acceptance_is_not_delivery(self):
        response = {"return": {"status": 200}, "entries": [{"messageid": 123, "status": 1}]}
        with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(200, response)) as request:
            result = self.send()
        self.assertEqual(result.status, "accepted")
        self.assertFalse(result.summary["delivered"])
        self.assertFalse(result.summary["answered"])
        self.assertEqual(result.provider_reference, hashlib.sha256(b"123").hexdigest())
        args = request.call_args.args
        self.assertEqual(args[:2], ("api.kavenegar.com", 443))
        self.assertEqual(args[3], "/v1/ownedfixturekey0123456789/sms/send.json")
        self.assertEqual(parse_qs(args[4].decode())["receptor"], [self.phone])
        self.assertEqual(request.call_count, 1)

    def test_template_otp_token_is_explicit_and_not_replaced_by_hash(self):
        provider = {**self.provider, "config": {"sender": "1000123", "template_id": "owned-template"}}
        response = {"return": {"status": 200}, "entries": [{"messageid": 124}]}
        with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(200, response)) as request:
            result = self.send(provider=provider, template_token="123456")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(parse_qs(request.call_args.args[4].decode())["token"], ["123456"])
        self.assertTrue(request.call_args.args[3].endswith("/verify/lookup.json"))

    def test_alert_with_otp_template_still_sends_full_sms_message(self):
        provider = {**self.provider, "config": {"sender": "1000123", "template_id": "owned-template"}}
        response = {"return": {"status": 200}, "entries": [{"messageid": 125}]}
        with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(200, response)) as request:
            result = self.send(provider=provider)
        self.assertEqual(result.status, "accepted")
        self.assertTrue(request.call_args.args[3].endswith("/sms/send.json"))
        self.assertEqual(parse_qs(request.call_args.args[4].decode())["message"], ["Owned alert"])

    def test_timeout_or_malformed_response_is_unknown_once_without_leaks(self):
        for error in (TimeoutError("secret=ownedfixturekey0123456789 recipient=" + self.phone), ValueError("private-response")):
            with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", side_effect=error) as request:
                result = self.send()
            self.assertEqual(result.status, "unknown")
            self.assertEqual(request.call_count, 1)
            public = json.dumps(result.summary)
            self.assertNotIn(self.phone, public)
            self.assertNotIn(self.secret["api_key"], public)
            self.assertNotIn("private-response", public)

    def test_missing_or_malformed_provider_return_status_is_unknown(self):
        for payload in ({}, {"return": {}}, {"return": {"status": "200"}}, {"return": {"status": True}},
                        {"return": {"status": 999}}, {"return": {"status": 409}}):
            with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(200, payload)) as request:
                self.assertEqual(self.send().status, "unknown")
                self.assertEqual(request.call_count, 1)
        with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(200, {"return": {"status": 418}})):
            self.assertEqual(self.send().status, "failed")

    def test_provider_rejection_and_ambiguous_status_do_not_retry(self):
        for status, expected in ((400, "failed"), (409, "unknown"), (429, "unknown"), (503, "unknown")):
            with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(status, {})) as request:
                self.assertEqual(self.send().status, expected)
                self.assertEqual(request.call_count, 1)

    def test_ssrf_special_addresses_are_never_allowlisted(self):
        for address in ("127.0.0.1", "169.254.169.254", "169.254.170.2", "100.100.100.200",
                        "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "ff02::1", "::ffff:127.0.0.1", "fd00:ec2::254", "168.63.129.16", "147.75.207.207"):
            with self.subTest(address=address), self.assertRaises(t.TransportConfigurationError):
                t._allowed_address(address, "0.0.0.0/0,::/0")

    def test_private_pbx_requires_explicit_server_cidr(self):
        with self.assertRaises(t.TransportConfigurationError): t._allowed_address("10.24.1.3", "")
        with self.assertRaises(t.TransportConfigurationError): t._allowed_address("10.24.2.3", "10.24.1.0/24")
        self.assertEqual(t._allowed_address("10.24.1.3", "10.24.1.0/24"), "10.24.1.3")
        self.assertEqual(t._allowed_address("8.8.8.8", ""), "8.8.8.8")

    def test_mixed_dns_is_rejected_instead_of_selecting_public_answer(self):
        records = [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("10.1.2.3", 443))]
        with patch.object(t.socket, "getaddrinfo", return_value=records), self.assertRaises(t.TransportConfigurationError):
            t.resolve_addresses("pbx.example.invalid", 443)

    def test_ari_origin_config_disallows_uri_and_dial_injection(self):
        good = {"endpoint": "https://pbx.example.invalid:8089/ari", "trunk": "owned-trunk", "ari_app": "owned-app"}
        self.assertEqual(t.validate_provider_config("voip", "asterisk_ari", good), good)
        for change in ({"endpoint": "http://pbx.example.invalid"}, {"endpoint": "https://u:p@pbx.example.invalid"},
                       {"endpoint": "https://pbx.example.invalid/ari?secret=x"}, {"endpoint": "https://pbx.example.invalid/free/path"},
                       {"trunk": "Local/1@context"}, {"trunk": "x;System(command)"}, {"dial_endpoint_template": "PJSIP/{phone}"},
                       {"trunk": None}, {"trunk": 123},
                       {"context": "also-context", "extension": "100"}, {"endpoint": "https://" + "a" * 64 + ".invalid/ari"}):
            with self.subTest(change=change), self.assertRaises(t.TransportConfigurationError):
                t.validate_provider_config("voip", "asterisk_ari", good | change)

    def test_ari_uses_deterministic_channel_and_fixed_trunk(self):
        provider = {"enabled": True, "provider_id": "asterisk_ari", "config": {
            "endpoint": "https://pbx.example.invalid/ari", "trunk": "owned-trunk", "context": "owned", "extension": "100"}}
        channel_id = "nerkhbaan-" + hashlib.sha256(b"owned-key").hexdigest()
        with patch.object(t, "resolve_addresses", return_value=frozenset({"8.8.8.8"})), patch.object(t, "_request", return_value=(200, {"id": channel_id})) as request:
            result = self.send(channel="voip", provider=provider, secret={"username": "owned", "password": "owned-fixture"})
        self.assertEqual(result.status, "accepted")
        self.assertEqual(request.call_args.args[3], "/ari/channels/" + channel_id)
        body = json.loads(request.call_args.args[4])
        self.assertEqual(body["endpoint"], "PJSIP/" + self.phone + "@owned-trunk")
        self.assertEqual(body["timeout"], 20)
        self.assertNotIn("app", body)

    def test_ip_pinning_preserves_hostname_and_closes_unvetted_peer(self):
        context, plain = MagicMock(), MagicMock()
        plain.getpeername.return_value = ("8.8.8.8", 443)
        with patch.object(t.ssl, "create_default_context", return_value=context), patch.object(t.socket, "create_connection", return_value=plain) as connect:
            client = t._PinnedConnection("api.kavenegar.com", 443, frozenset({"8.8.8.8", "2001:4860:4860::8888"}), t.time.monotonic() + 12)
            client.connect()
        self.assertEqual(connect.call_args.args[0], ("8.8.8.8", 443))
        context.wrap_socket.assert_called_once_with(plain, server_hostname="api.kavenegar.com")
        plain.getpeername.return_value = ("127.0.0.1", 443)
        with patch.object(t.socket, "create_connection", return_value=plain), self.assertRaises(t.TransportConfigurationError): client.connect()
        plain.close.assert_called_once()

    def test_no_redirect_and_response_size_bounded(self):
        for redirect in (True, False):
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = 302 if redirect else 200
            response.read1.return_value = b"x" * 4096
            with patch.object(t, "_PinnedConnection", return_value=connection), patch.object(t.threading, "Timer"), self.assertRaises(t.TransportConfigurationError):
                t._request("api.kavenegar.com", 443, frozenset({"8.8.8.8"}), "/owned", b"", {})
            connection.close.assert_called_once()
            if redirect: response.read1.assert_not_called()

    def test_dns_pool_exhaustion_fails_without_spawning_or_sending(self):
        slots = MagicMock(); slots.acquire.return_value = False
        with patch.object(t, "_DNS_SLOTS", slots), patch.object(t.threading, "Thread") as thread:
            with self.assertRaises(t.TransportConfigurationError): t.resolve_addresses("pbx.example.invalid", 443)
        thread.assert_not_called()
        slots.acquire.assert_called_once_with(timeout=t.DNS_SECONDS)


if __name__ == "__main__":
    unittest.main()
