from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch

import jwt

os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-contract-key-0000000000000000000000000000000000000000")

from app.config import settings
from app.security import create_access_token, decode_access_claims


class JwtContractTests(unittest.TestCase):
    def setUp(self):
        self.key = "test-only-jwt-contract-key-0000000000000000000000000000000000000000"
        self.patches = [patch.object(settings, field, value) for field, value in {
            "jwt_secret_key": self.key, "jwt_algorithm": "HS256", "jwt_issuer": "contract-test", "jwt_audience": "contract-client",
        }.items()]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        now = int(time.time())
        self.claims = {"sub": "7", "iss": "contract-test", "aud": "contract-client", "iat": now, "nbf": now, "exp": now + 300, "jti": "contract-id", "type": "access", "sv": 1, "sid": "contract-session"}

    def token(self, changes=None):
        return jwt.encode({**self.claims, **(changes or {})}, self.key, algorithm="HS256")

    def test_old_hmac_wire_format_and_new_tokens_remain_compatible(self):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
        message = encode({"alg": "HS256", "typ": "JWT"}) + b"." + encode(self.claims)
        signature = base64.urlsafe_b64encode(hmac.new(self.key.encode(), message, hashlib.sha256).digest()).rstrip(b"=")
        self.assertEqual(decode_access_claims((message + b"." + signature).decode()), self.claims)
        self.assertEqual(decode_access_claims(create_access_token("7", session_id="contract-session"))["sid"], "contract-session")

    def test_every_required_claim_is_enforced(self):
        for required in ("aud", "exp", "iat", "iss", "jti", "nbf", "sub"):
            with self.subTest(claim=required):
                claims = {key: value for key, value in self.claims.items() if key != required}
                self.assertIsNone(decode_access_claims(jwt.encode(claims, self.key, algorithm="HS256")))

    def test_invalid_identity_time_type_and_algorithm_are_rejected(self):
        for changes in ({"aud": "other-client"}, {"iss": "other-issuer"}, {"exp": 1}, {"nbf": int(time.time()) + 300}, {"iat": int(time.time()) + 300}, {"sub": 7}, {"type": "refresh"}):
            with self.subTest(changes=changes):
                self.assertIsNone(decode_access_claims(self.token(changes)))
        self.assertIsNone(decode_access_claims(jwt.encode(self.claims, self.key, algorithm="HS384")))
        self.assertIsNone(decode_access_claims(jwt.encode(self.claims, "", algorithm="none")))
        self.assertIsNone(decode_access_claims("bad.token.parts"))
        self.assertIsNone(decode_access_claims("x" * 4097))


if __name__ == "__main__":
    unittest.main()
