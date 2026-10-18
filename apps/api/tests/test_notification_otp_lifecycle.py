from __future__ import annotations

import os
import re
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault('JWT_SECRET_KEY', 'notification-lifecycle-test-not-for-runtime-0000000000')

from app.models import NotificationPreference, OtpVerification, User
from app.routers import notifications


FROZEN_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
TEST_DATABASE_URL = os.getenv('TEST_DATABASE_URL')
TABLES = (User.__table__, NotificationPreference.__table__, OtpVerification.__table__)


class _CountedSession(Session):
    commits = 0

    def commit(self) -> None:
        self.commits += 1
        super().commit()


class _LifecycleCases:
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(notifications, 'datetime', SimpleNamespace(now=lambda _tz=None: self.now)))
        self.enterContext(patch.object(notifications, 'rate_limit_hit', return_value=SimpleNamespace(blocked=False)))
        self.enterContext(patch.object(notifications, 'rate_limit_clear'))
        self.enterContext(patch.object(notifications, 'hash_password', side_effect=lambda code: 'fixture:'+code))
        self.enterContext(patch.object(notifications, 'verify_password', side_effect=lambda code, hashed: hashed == 'fixture:'+code))
        self.mail = self.enterContext(patch.object(notifications, 'send_email', return_value=True))
        with self.factory() as db:
            db.add(User(id=1, username='otp_owner', full_name='Fixture owner', email='owner@example.com', password_hash='fixture', is_active=True))
            db.add(User(id=2, username='otp_peer', full_name='Fixture peer', email='peer@example.com', password_hash='fixture', is_active=True))
            db.commit()

    def issue(self, code='111111', destination='one@example.com', factory=None):
        with (factory or self.factory)() as db, patch.object(notifications.secrets, 'randbelow', return_value=int(code)):
            return notifications.start_otp(notifications.OtpStartRequest(channel='email', destination=destination), SimpleNamespace(id=1), db)

    def confirm(self, code='111111', destination='one@example.com', factory=None):
        with (factory or self.factory)() as db:
            return notifications.confirm_otp(notifications.OtpConfirmRequest(channel='email', destination=destination, code=code), SimpleNamespace(id=1), db)

    def disable(self, factory=None):
        with (factory or self.factory)() as db:
            return notifications.disable_channel('email', SimpleNamespace(id=1), db)

    def assert_rejected(self, code='111111', destination='one@example.com'):
        with self.assertRaises(HTTPException) as raised:
            self.confirm(code, destination)
        self.assertEqual(raised.exception.status_code, 400)

    def rows(self):
        with self.factory() as db:
            return db.scalars(select(OtpVerification).order_by(OtpVerification.id)).all()

    def test_old_code_cannot_reactivate_after_new_code_and_disable(self):
        self.issue('111111'); self.issue('222222')
        self.assertEqual([row.used for row in self.rows()], [True, False])
        self.assertTrue(self.confirm('222222').email_verified)
        self.assertFalse(self.disable().email_enabled)
        self.assert_rejected('111111')
        with self.factory() as db:
            prefs = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == 1))
            self.assertFalse(prefs.email_enabled or prefs.email_verified)
        self.assertTrue(all(row.used for row in self.rows()))

    def test_only_latest_destination_can_be_confirmed(self):
        self.issue('111111', 'one@example.com'); self.issue('222222', 'two@example.com')
        self.assert_rejected('111111', 'one@example.com')
        self.assertEqual(self.confirm('222222', 'two@example.com').email_address, 'two@example.com')

    def test_failed_reissue_does_not_restore_previous_code(self):
        self.issue('111111'); self.mail.return_value = False
        with self.assertRaises(HTTPException) as raised:
            self.issue('222222')
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(len(self.rows()), 1)
        self.assertTrue(self.rows()[0].used)
        self.assert_rejected('111111')

    def test_failed_delivery_keeps_a_concurrent_newer_challenge(self):
        self.issue('333333')
        def delivery_result(*_args):
            if self.mail.call_count == 2:
                self.issue('222222')
                return False
            return True
        self.mail.side_effect = delivery_result
        with self.assertRaises(HTTPException) as raised:
            self.issue('111111')
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual([row.used for row in self.rows()], [True, False])
        self.assertEqual(self.rows()[-1].code_hash, 'fixture:222222')
        self.assert_rejected('333333')
        self.assertTrue(self.confirm('222222').email_verified)

    def test_consuming_latest_also_invalidates_legacy_older_destinations(self):
        with self.factory() as db:
            db.add_all([OtpVerification(user_id=1, channel='email', destination=destination,
                        code_hash='fixture:'+code, expires_at=self.now+timedelta(minutes=5), used=False)
                        for destination, code in [('one@example.com', '111111'), ('two@example.com', '222222')]])
            db.commit()
        self.confirm('222222', 'two@example.com')
        self.assertTrue(all(row.used for row in self.rows()))
        self.assert_rejected('111111', 'one@example.com')

    def test_used_latest_never_exposes_an_unused_legacy_code(self):
        with self.factory() as db:
            db.add_all([OtpVerification(user_id=1, channel='email', destination='one@example.com',
                        code_hash='fixture:'+code, expires_at=self.now+timedelta(minutes=5), used=used)
                        for code, used in [('111111', False), ('222222', True)]])
            db.commit()
        self.assert_rejected('111111')

    def test_expired_and_consumed_codes_stay_rejected(self):
        self.issue()
        with self.factory() as db:
            row = db.scalar(select(OtpVerification)); row.expires_at = self.now-timedelta(seconds=1); db.commit()
        self.assert_rejected()
        self.issue('222222'); self.confirm('222222'); self.assert_rejected('222222')

    def test_invalidation_stays_with_owner_and_channel(self):
        with self.factory() as db:
            db.add_all([OtpVerification(user_id=owner, channel=channel, destination='one@example.com',
                        code_hash='fixture:123456', expires_at=self.now+timedelta(minutes=5), used=False)
                        for owner, channel in [(1, 'email'), (1, 'sms'), (2, 'email')]])
            db.commit()
        self.issue(); self.disable()
        with self.factory() as db:
            remaining = db.scalars(select(OtpVerification).where(OtpVerification.used.is_(False))).all()
            self.assertEqual({(row.user_id, row.channel) for row in remaining}, {(1, 'sms'), (2, 'email')})

    def test_first_preference_and_consumption_share_one_commit(self):
        self.issue()
        with self.factory() as db:
            notifications.confirm_otp(notifications.OtpConfirmRequest(channel='email', destination='one@example.com', code='111111'), SimpleNamespace(id=1), db)
            self.assertEqual(db.commits, 1)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count(NotificationPreference.id))), 1)
            self.assertTrue(db.scalar(select(OtpVerification)).used)


class NotificationOTPLifecycleTests(_LifecycleCases, unittest.TestCase):
    def setUp(self):
        self.now = FROZEN_NOW.replace(tzinfo=None)
        self.engine = create_engine('sqlite://')
        metadata = MetaData()
        for table in TABLES:
            table.to_metadata(metadata)
        metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, class_=_CountedSession, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        super().setUp()


@unittest.skipUnless(TEST_DATABASE_URL, 'TEST_DATABASE_URL is not set')
class NotificationOTPPostgresTests(_LifecycleCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_DATABASE_URL)
        if url.get_backend_name() != 'postgresql' or set(re.split(r'[_-]+', (url.database or '').lower())).isdisjoint({'test', 'ci'}):
            raise unittest.SkipTest('An isolated PostgreSQL test or CI database is required')
        cls.schema = 'notification_otp_'+uuid.uuid4().hex
        cls.admin = create_engine(url)
        quoted = cls.admin.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {quoted}'))
        metadata = MetaData()
        for table in TABLES:
            table.to_metadata(metadata, schema=cls.schema)
        metadata.create_all(cls.admin)
        cls.engine = create_engine(url, connect_args={'options': f'-csearch_path={cls.schema},public -clock_timeout=10000 -cstatement_timeout=15000'})
        cls.factory = sessionmaker(bind=cls.engine, class_=_CountedSession, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        quoted = cls.admin.dialect.identifier_preparer.quote(cls.schema)
        try:
            with cls.admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {quoted} CASCADE'))
        finally:
            cls.admin.dispose()

    def setUp(self):
        self.now = FROZEN_NOW
        with self.engine.begin() as connection:
            for table in reversed(TABLES):
                connection.execute(table.delete())
        super().setUp()

    def race(self, first_operation, second_operation):
        held, release, attempting = threading.Event(), threading.Event(), threading.Event()
        second_pid = []
        class LockedSession(_CountedSession):
            def scalar(inner, statement, *args, **kwargs):
                columns = getattr(statement, 'column_descriptions', [])
                owner_lock = getattr(statement, '_for_update_arg', None) is not None and columns and columns[0].get('entity') is User
                if owner_lock and inner.info.get('second') and not attempting.is_set():
                    second_pid.append(inner.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one())
                    attempting.set()
                result = super().scalar(statement, *args, **kwargs)
                if owner_lock and inner.info.get('first') and not inner.info.get('gate_seen'):
                    inner.info['gate_seen'] = True; held.set()
                    if not release.wait(8):
                        raise AssertionError('Owner lock was not released by fixture')
                return result

        first_factory = sessionmaker(bind=self.engine, class_=LockedSession, expire_on_commit=False, info={'first': True})
        second_factory = sessionmaker(bind=self.engine, class_=LockedSession, expire_on_commit=False, info={'second': True})
        def perform(operation, factory):
            try:
                operation(factory)
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(perform, first_operation, first_factory)
            try:
                self.assertTrue(held.wait(3), 'First request did not acquire owner lock')
                second = pool.submit(perform, second_operation, second_factory)
                self.assertTrue(attempting.wait(3), 'Second request did not attempt owner lock')
                deadline = time.monotonic()+3; blocked = False
                while time.monotonic() < deadline:
                    with self.admin.connect() as connection:
                        wait = connection.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'), {'pid': second_pid[0]}).scalar_one()
                    if wait == 'Lock':
                        blocked = True; break
                    time.sleep(0.025)
                self.assertTrue(blocked, 'Second request was not blocked by real PostgreSQL owner lock')
                self.assertFalse(second.done())
            finally:
                release.set()
            return first.result(timeout=8), second.result(timeout=8)

    def test_parallel_confirmation_consumes_once_with_first_preferences(self):
        self.issue()
        confirm = lambda factory: self.confirm(factory=factory)
        self.assertEqual(self.race(confirm, confirm), (200, 400))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count(NotificationPreference.id))), 1)
            self.assertTrue(db.scalar(select(OtpVerification)).used)

    def test_confirmation_and_disable_follow_owner_lock_order(self):
        for first_disable in (False, True):
            with self.subTest(first_disable=first_disable):
                self.setUp(); self.issue()
                confirm = lambda factory: self.confirm(factory=factory)
                disable = lambda factory: self.disable(factory=factory)
                operations = (disable, confirm) if first_disable else (confirm, disable)
                self.assertEqual(self.race(*operations), (200, 400) if first_disable else (200, 200))
                with self.factory() as db:
                    prefs = db.scalar(select(NotificationPreference)); self.assertFalse(prefs.email_enabled or prefs.email_verified)
                self.assertTrue(all(row.used for row in self.rows()))

    def test_reissue_and_confirmation_follow_owner_lock_order(self):
        for first_reissue in (False, True):
            with self.subTest(first_reissue=first_reissue):
                self.setUp(); self.issue()
                confirm = lambda factory: self.confirm(factory=factory)
                reissue = lambda factory: self.issue('222222', factory=factory)
                self.assertEqual(self.race(reissue, confirm) if first_reissue else self.race(confirm, reissue), (200, 400) if first_reissue else (200, 200))
                self.assert_rejected('111111')
                self.assertEqual([row.used for row in self.rows()], [True, False])

    def test_reissue_and_disable_follow_owner_lock_order(self):
        for first_disable in (False, True):
            with self.subTest(first_disable=first_disable):
                self.setUp(); self.issue()
                disable = lambda factory: self.disable(factory=factory)
                reissue = lambda factory: self.issue('222222', factory=factory)
                self.assertEqual(self.race(disable, reissue) if first_disable else self.race(reissue, disable), (200, 200))
                self.assert_rejected('111111')
                with self.factory() as db:
                    prefs = db.scalar(select(NotificationPreference)); self.assertFalse(prefs.email_enabled or prefs.email_verified)
                self.assertEqual([row.used for row in self.rows()], [True, not first_disable])

    def test_first_default_preferences_and_confirmation_share_creation_lock(self):
        self.issue()
        def preferences(factory):
            with factory() as db:
                notifications._prefs_for(db, 1)
        self.assertEqual(self.race(preferences, lambda factory: self.confirm(factory=factory)), (200, 200))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count(NotificationPreference.id))), 1)
            self.assertTrue(db.scalar(select(NotificationPreference)).email_verified)

    def test_transactional_preferences_share_the_confirmation_creation_lock(self):
        self.issue()
        def preferences(factory):
            with factory() as db:
                notifications._prefs_for_transaction(db, 1)
                self.assertEqual(db.commits, 0)
                db.commit()
        self.assertEqual(self.race(preferences, lambda factory: self.confirm(factory=factory)), (200, 200))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count(NotificationPreference.id))), 1)
            self.assertTrue(db.scalar(select(NotificationPreference)).email_verified)

    def test_first_preferences_lock_before_flushing_pending_owner_references(self):
        queried = threading.Barrier(2)

        class PendingSession(_CountedSession):
            def scalar(inner, statement, *args, **kwargs):
                columns = getattr(statement, 'column_descriptions', [])
                result = super().scalar(statement, *args, **kwargs)
                if columns and columns[0].get('entity') is NotificationPreference and not inner.info.get('first_lookup_seen'):
                    inner.info['first_lookup_seen'] = True
                    queried.wait(timeout=5)
                return result

        factory = sessionmaker(bind=self.engine, class_=PendingSession, expire_on_commit=False)
        def create_preferences(index):
            with factory() as db:
                db.add(OtpVerification(user_id=1, channel='telegram', destination=str(index),
                       code_hash='fixture:111111', expires_at=self.now+timedelta(minutes=5), used=False))
                notifications._prefs_for(db, 1)
                db.commit()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(create_preferences, 1)
            second = pool.submit(create_preferences, 2)
            first.result(timeout=8); second.result(timeout=8)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count(NotificationPreference.id))), 1)
            self.assertEqual(db.scalar(select(func.count(OtpVerification.id))), 2)


if __name__ == '__main__':
    unittest.main()
