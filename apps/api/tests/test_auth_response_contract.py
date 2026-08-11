from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")
os.environ["DEBUG"] = "false"

from app.config import settings
from app.routers.auth import _client_access_token


class AuthResponseContractTests(unittest.TestCase):
    def test_cookie_browser_does_not_receive_body_token(self) -> None:
        request = SimpleNamespace(headers={})
        with patch.object(settings, "auth_cookie_enabled", True), patch.object(
            settings, "auth_return_bearer_token", True
        ):
            self.assertIsNone(_client_access_token(request, "secret-token"))

    def test_desktop_receives_body_token(self) -> None:
        request = SimpleNamespace(headers={"x-client-type": "desktop"})
        with patch.object(settings, "auth_cookie_enabled", True), patch.object(
            settings, "auth_return_bearer_token", True
        ):
            self.assertEqual(_client_access_token(request, "secret-token"), "secret-token")
