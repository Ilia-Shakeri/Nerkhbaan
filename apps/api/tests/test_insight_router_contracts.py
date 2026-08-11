from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")
os.environ["DEBUG"] = "false"

from app.routers.insights import ChatMessage, ChatRequest, chat
from app.services.insights import InsightUnavailableError


class InsightRouterContractTests(unittest.IsolatedAsyncioTestCase):
    def test_chat_requires_user_message_last(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(messages=[ChatMessage(role="assistant", content="old reply")])

    async def test_failed_new_chat_does_not_create_blank_session(self) -> None:
        payload = ChatRequest(messages=[ChatMessage(role="user", content="price view")])
        db = MagicMock()
        db.scalars.return_value.all.return_value = []

        with patch("app.routers.insights._enforce_rate_limit"), patch.object(
            __import__("app.routers.insights", fromlist=["insight_engine"]).insight_engine,
            "chat",
            AsyncMock(side_effect=InsightUnavailableError("source down")),
        ):
            with self.assertRaises(Exception) as raised:
                await chat(payload, SimpleNamespace(id=42), db)

        self.assertEqual(getattr(raised.exception, "status_code", None), 503)
        db.add.assert_not_called()
        db.commit.assert_not_called()
