from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('JWT_SECRET_KEY', 'push-delivery-test-not-for-runtime-0000000000000')

from pywebpush import WebPushException
from requests.exceptions import ConnectTimeout, ConnectionError, ReadTimeout, SSLError

from app.services import alert_engine
from app.services.alert_engine import AlertEngine, PermanentDeliveryError, SourceRightsDeliveryError


class PushDeliveryFailureTests(unittest.TestCase):
    def send(
        self,
        statuses: tuple[int | Exception, ...],
        expected: type[Exception] | None,
        *,
        attempted: int | None = None,
        rights: tuple[bool, ...] | None = None,
    ) -> None:
        endpoints = [f'https://push.fixture.invalid/{index}' for index in range(len(statuses))]
        subscriptions = [SimpleNamespace(endpoint=endpoint, p256dh='fixture-key', auth='fixture-auth')
                         for endpoint in endpoints]
        db = Mock()
        db.scalar.return_value = SimpleNamespace(push_app=True, silent_mode=False)
        db.scalars.return_value.all.return_value = subscriptions
        engine = AlertEngine()
        results = [status if isinstance(status, Exception) else
                   SimpleNamespace(status_code=status) if status == 201 else
                   WebPushException('Fixture push failure', response=SimpleNamespace(status_code=status))
                   for status in statuses]
        with ExitStack() as stack:
            stack.enter_context(patch.object(alert_engine.settings, 'vapid_private_key', 'fixture-private'))
            stack.enter_context(patch.object(alert_engine.settings, 'vapid_public_key', 'fixture-public'))
            stack.enter_context(patch.object(alert_engine, 'SessionLocal', return_value=db))
            stack.enter_context(patch.object(alert_engine, 'source_rights_snapshot_allowed',
                                            **({'return_value': True} if rights is None else {'side_effect': rights})))
            stack.enter_context(patch.object(engine, '_alert_summary', return_value=('Fixture', 'Fixture alert')))
            stack.enter_context(patch.object(engine, '_selected_price_context', return_value={}))
            stack.enter_context(patch.object(engine, '_formula_price_contexts', return_value=[]))
            transport = stack.enter_context(patch('pywebpush.webpush', side_effect=results))
            prune = stack.enter_context(patch.object(engine, '_prune_subscriptions'))
            send = lambda: asyncio.run(engine._send_push_notification(
                SimpleNamespace(id=1, user_id=1, asset_id='BTC_USD'), {'assets': []}))
            if expected is None:
                send()
            else:
                with self.assertRaises(expected) as raised:
                    send()
                self.assertIs(type(raised.exception), expected)
            calls = len(statuses) if attempted is None else attempted
            self.assertEqual(transport.call_count, calls)
            self.assertEqual([call.kwargs['subscription_info']['endpoint'] for call in transport.call_args_list], endpoints[:calls])
            expired = [endpoint for endpoint, status in zip(endpoints[:calls], statuses[:calls])
                       if status in (404, 410)]
            if expired:
                prune.assert_called_once_with(expired)
            else:
                prune.assert_not_called()
        db.close.assert_called_once()

    def test_all_gone_is_permanent(self) -> None:
        for statuses in ((404, 410), (410, 404), (404, 404), (410, 410)):
            with self.subTest(statuses=statuses):
                self.send(statuses, PermanentDeliveryError)

    def test_only_temporary_failure_is_retryable(self) -> None:
        self.send((503, 503), RuntimeError)

    def test_mixed_gone_and_temporary_keeps_remaining_target_retryable(self) -> None:
        for statuses in ((410, 503), (503, 410), (404, 500), (500, 404)):
            with self.subTest(statuses=statuses):
                self.send(statuses, RuntimeError)

    def test_success_is_accepted_in_either_position(self) -> None:
        for failure in (404, 410, 503):
            for statuses in ((failure, 201), (201, failure)):
                with self.subTest(statuses=statuses):
                    self.send(statuses, None)

    def test_timeout_before_success_does_not_block_remaining_target(self) -> None:
        self.send((ConnectTimeout('Fixture timeout'), 201), None)

    def test_success_before_timeout_stays_accepted(self) -> None:
        self.send((201, ConnectTimeout('Fixture timeout')), None)

    def test_all_timeout_remains_retryable(self) -> None:
        self.send((ConnectTimeout('Fixture connect timeout'), ReadTimeout('Fixture read timeout')), RuntimeError)

    def test_connection_and_tls_errors_do_not_block_other_targets(self) -> None:
        for error in (ConnectionError, ReadTimeout, SSLError):
            for statuses in ((error('Fixture transport failure'), 201), (201, error('Fixture transport failure'))):
                with self.subTest(statuses=statuses):
                    self.send(statuses, None)

    def test_timeout_and_expired_target_remain_retryable(self) -> None:
        for statuses in ((ConnectTimeout('Fixture timeout'), 410), (410, ConnectTimeout('Fixture timeout'))):
            with self.subTest(statuses=statuses):
                self.send(statuses, RuntimeError)

    def test_source_rights_failure_is_not_treated_as_transport_failure(self) -> None:
        self.send((201, 201), SourceRightsDeliveryError, attempted=1, rights=(True, False))

    def test_failure_logs_exclude_endpoint_and_response_details(self) -> None:
        marker = 'fixture-private-endpoint-and-response-details'
        errors = (
            ConnectTimeout(marker),
            WebPushException(marker, response=SimpleNamespace(status_code=503)),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with self.assertLogs(alert_engine.logger, level='ERROR') as captured:
                    self.send((error, 201), None)
                self.assertNotIn(marker, '\n'.join(captured.output))


if __name__ == '__main__':
    unittest.main()
