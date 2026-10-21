from __future__ import annotations

import os
import smtplib
import unittest
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('JWT_SECRET_KEY', 'smtp-delivery-fixture-not-for-runtime-000000000000')

from app import security


class SMTPDeliveryAcceptanceTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(smtp_host='mail.fixture.invalid', smtp_port=465,
                               smtp_username='fixture-user', smtp_password='fixture-password',
                               smtp_from='alerts@fixture.invalid', smtp_use_tls=True, debug=False)

    def message(self):
        message = EmailMessage()
        message['From'] = 'alerts@fixture.invalid'
        message['To'] = 'recipient@fixture.invalid'
        message['Subject'] = 'Owned delivery fixture'
        message.set_content('Owned delivery fixture')
        return message

    def client(self, *, quit_result=(221, b'closing'), quit_error=None, send_error=None):
        client = smtplib.SMTP.__new__(smtplib.SMTP)
        client.ehlo_resp = b'fixture-ready'
        client.helo_resp = None
        client.esmtp_features = {}
        client.does_esmtp = True
        client.sock = SimpleNamespace(close=Mock())
        client.file = SimpleNamespace(close=Mock())
        client.login = Mock()
        client.sendmail = Mock(return_value={}, side_effect=send_error)
        client.docmd = Mock(return_value=quit_result, side_effect=quit_error)
        return client

    def test_data_accepted_then_quit_rejected_does_not_request_a_duplicate(self):
        client = self.client(quit_result=(421, b'closing after accepted data'))
        with patch.object(security, 'settings', self.config()), \
                patch.object(security.smtplib, 'SMTP_SSL', return_value=client):
            self.assertTrue(security.send_email('recipient@fixture.invalid', 'Verify', 'Fixture code'))
        client.sendmail.assert_called_once()
        self.assertIsNone(client.sock)
        self.assertIsNone(client.file)

    def test_data_accepted_then_quit_timeout_stays_accepted_and_closes(self):
        client = self.client(quit_error=TimeoutError('owned fixture cleanup timeout'))
        with patch.object(security, 'settings', self.config()), \
                patch.object(security.smtplib, 'SMTP_SSL', return_value=client):
            self.assertTrue(security.send_email('recipient@fixture.invalid', 'Verify', 'Fixture code'))
        client.sendmail.assert_called_once()
        self.assertIsNone(client.sock)
        self.assertIsNone(client.file)

    def test_data_rejection_keeps_primary_error_when_quit_also_fails(self):
        primary = smtplib.SMTPDataError(451, b'owned fixture temporary rejection')
        client = self.client(quit_result=(421, b'owned fixture cleanup failure'), send_error=primary)
        with patch.object(security.smtplib, 'SMTP_SSL', return_value=client), \
                self.assertRaises(smtplib.SMTPDataError) as raised:
            security.send_smtp_message(self.message(), smtp_settings=self.config())
        self.assertIs(raised.exception, primary)
        self.assertIsNone(client.sock)
        self.assertIsNone(client.file)

    def test_authentication_failure_cannot_be_hidden_by_cleanup_failure(self):
        primary = smtplib.SMTPAuthenticationError(535, b'owned fixture authentication rejection')
        client = self.client(quit_error=TimeoutError('owned fixture cleanup timeout'))
        client.login.side_effect = primary
        with patch.object(security.smtplib, 'SMTP_SSL', return_value=client), \
                self.assertRaises(smtplib.SMTPAuthenticationError) as raised:
            security.send_smtp_message(self.message(), smtp_settings=self.config())
        self.assertIs(raised.exception, primary)
        client.sendmail.assert_not_called()
        self.assertIsNone(client.sock)
        self.assertIsNone(client.file)

    def test_acceptance_and_graceful_quit_keep_the_single_destination(self):
        client = self.client()
        with patch.object(security.smtplib, 'SMTP_SSL', return_value=client):
            security.send_smtp_message(self.message(), smtp_settings=self.config())
        client.sendmail.assert_called_once()
        self.assertEqual(client.sendmail.call_args.args[0], 'alerts@fixture.invalid')
        self.assertEqual(client.sendmail.call_args.args[1], ['recipient@fixture.invalid'])
        self.assertIsNone(client.sock)
        self.assertIsNone(client.file)


class SMTPConfigurationFailureTests(unittest.TestCase):
    def config(self, **changes):
        values = {'smtp_host': 'mail.fixture.invalid', 'smtp_port': 587,
                  'smtp_username': 'fixture-user', 'smtp_password': 'fixture-password',
                  'smtp_from': 'alerts@fixture.invalid', 'smtp_use_tls': True, 'debug': False}
        return SimpleNamespace(**(values | changes))

    def test_partial_authentication_cannot_fall_back_to_anonymous_submission(self):
        for changes in [{'smtp_username': None}, {'smtp_password': None}, {'smtp_password': ''}]:
            with self.subTest(changes=changes), patch.object(security, 'settings', self.config(**changes)), \
                    patch.object(security.smtplib, 'SMTP') as plain, \
                    patch.object(security.smtplib, 'SMTP_SSL') as encrypted:
                self.assertFalse(security.send_email('recipient@fixture.invalid', 'Verify', 'Fixture code'))
                plain.assert_not_called()
                encrypted.assert_not_called()

    def test_authentication_cannot_send_credentials_without_tls(self):
        with patch.object(security, 'settings', self.config(smtp_port=25, smtp_use_tls=False)), \
                patch.object(security.smtplib, 'SMTP') as plain, \
                patch.object(security.smtplib, 'SMTP_SSL') as encrypted:
            self.assertFalse(security.send_email('recipient@fixture.invalid', 'Verify', 'Fixture code'))
        plain.assert_not_called()
        encrypted.assert_not_called()

    def test_explicit_anonymous_relay_does_not_gain_an_authentication_requirement(self):
        with patch.object(security, 'settings', self.config(smtp_port=25, smtp_use_tls=False,
                          smtp_username=None, smtp_password=None)), \
                patch.object(security.smtplib, 'SMTP') as plain:
            self.assertTrue(security.send_email('recipient@fixture.invalid', 'Verify', 'Fixture code'))
        plain.return_value.starttls.assert_not_called()
        plain.return_value.login.assert_not_called()
        plain.return_value.send_message.assert_called_once()

    def test_missing_host_remains_unavailable_without_a_transport_call(self):
        with patch.object(security, 'settings', self.config(smtp_host=None)), \
                patch.object(security.smtplib, 'SMTP') as plain, \
                patch.object(security.smtplib, 'SMTP_SSL') as encrypted:
            self.assertFalse(security.send_email('recipient@fixture.invalid', 'Verify', 'Fixture code'))
        plain.assert_not_called()
        encrypted.assert_not_called()


if __name__ == '__main__':
    unittest.main()
