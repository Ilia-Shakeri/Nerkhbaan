import unittest
from unittest.mock import MagicMock

from pydantic import ValidationError

from app.schemas import UserCreate
from app.routers.support import TicketCreate, MessageCreate, _record_consent
from app.routers.insights import ChatRequest


class PolicyConsentTests(unittest.TestCase):
    def account(self, **changes):
        values = dict(username="sample", email="sample@example.com", password="GoodPassword12",
                      accepted_terms=True, account_data_consent=True, policy_version="2026-09-19")
        values.update(changes)
        return UserCreate(**values)

    def test_display_name_is_optional(self):
        self.assertEqual(self.account().full_name, "")
        self.assertEqual(self.account(full_name="   ").full_name, "")
        self.assertEqual(self.account(full_name="  Nick  ").full_name, "Nick")
        with self.assertRaises(ValidationError):
            self.account(full_name="X")

    def test_missing_agreement_is_rejected(self):
        with self.assertRaises(ValidationError):
            UserCreate(username="sample", email="sample@example.com", password="GoodPassword12")

    def test_only_explicit_boolean_agreement_is_accepted(self):
        for field in ("accepted_terms", "account_data_consent"):
            for value in (False, None, 1, "true", "false"):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.account(**{field: value})

    def test_old_policy_cannot_be_silently_accepted(self):
        with self.assertRaises(ValidationError):
            self.account(policy_version="2020-01-01")

    def test_short_or_digit_free_password_fails(self):
        for password in ("Abcd12!x", "LongPassword!"):
            with self.assertRaises(ValidationError):
                self.account(password=password)

    def test_support_requires_permission_and_current_version(self):
        for model, payload in ((TicketCreate, {"subject": "Help", "message": "Question"}),
                               (MessageCreate, {"content": "Reply"})):
            with self.assertRaises(ValidationError):
                model(**payload)
            for value in (False, "true", 1):
                with self.assertRaises(ValidationError):
                    model(**payload, support_data_consent=value, policy_version="2026-09-19")
            self.assertTrue(model(**payload, support_data_consent=True,
                                  policy_version="2026-09-19").support_data_consent)

    def test_support_receipt_has_no_message_or_identifiers(self):
        db = MagicMock()
        _record_consent(db, 7, 12, "2026-09-19")
        event = db.add.call_args.args[0]
        self.assertEqual(event.user_id, 7)
        self.assertEqual(event.detail, {"policy_version": "2026-09-19", "ticket_id": 12,
                                       "support_data_consent": True})
        self.assertIsNone(event.ip_hash)
        self.assertIsNone(event.user_agent_hash)

    def test_chat_rejects_missing_or_false_processing_permission(self):
        for value in (False, None, 1, "true"):
            with self.assertRaises(ValidationError):
                ChatRequest(messages=[{"role": "user", "content": "Market question"}],
                            processing_consent=value, policy_version="2026-09-19")


if __name__ == "__main__":
    unittest.main()
