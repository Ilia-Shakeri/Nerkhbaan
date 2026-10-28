"""Telegram peer typing and cached canonical input revalidation."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('JWT_SECRET_KEY', 'telegram-unit-key-not-for-runtime-000000000000')
from app.admin.schemas import TelegramSourceCreate
from app.pricing.instruments import get_instrument
from app.pricing.models import CanonicalQuote, CanonicalStatus
from app.pricing.service import InstrumentPricingService
from app.pricing.telegram import StoredTelegramQuoteRepository


def summary():
    return {'provider_ids':['telegram:1'],'primary_provider_id':'telegram:1','derived':False}


class PeerSchemaTests(unittest.TestCase):
    def create(self, peer, kind):
        return TelegramSourceCreate(channel_id=peer, source_type=kind, display_name='Owned source',
            allowed_instruments=['USDT_TOMAN'], parser_version='strict-explicit-3', confirmation='owned test')

    def test_basic_group_is_not_rewritten_into_a_channel(self):
        self.assertEqual(self.create('-12345','group').channel_id, '-12345')
        self.assertEqual(self.create('-1001234','group').channel_id, '-1001234')
        self.assertFalse(self.create('-12345','group').enabled)

    def test_channel_legacy_positive_and_marked_identity(self):
        self.assertEqual(self.create('12345','channel').channel_id, '-10012345')
        self.assertEqual(self.create('-1000000000123','group').channel_id, '-1000000000123')

    def test_names_users_and_ambiguous_positive_groups_rejected(self):
        for peer, kind in [('public_channel','channel'),('0','channel'),('12345','group'),('-12345','channel')]:
            with self.subTest(peer=peer), self.assertRaises(ValueError):
                self.create(peer,kind)


class CachedInputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repository = StoredTelegramQuoteRepository()
        self.quote = SimpleNamespace(primary_quote_id=12,verification_quote_ids=[],source_summary=summary())
        self.instrument = get_instrument('USDT_TOMAN')
        self.rows = [{'id':12,'source_type':'telegram','instrument_id':'USDT_TOMAN'}]

    async def test_native_quote_does_not_add_a_telegram_database_dependency(self):
        self.quote.source_summary = {'provider_ids':['nobitex_usdt'],'primary_provider_id':'nobitex_usdt','derived':False}
        with patch.object(self.repository,'_input_rows') as read:
            self.assertTrue(await self.repository.canonical_inputs_valid(self.quote,self.instrument))
        read.assert_not_called()

    async def test_only_current_valid_input_can_certify_the_cache(self):
        fresh=SimpleNamespace(id=12,provider_id='telegram:1',metadata={'source_role':'fallback','source_identity':'origin-one'})
        with patch.object(self.repository,'_input_rows',return_value=self.rows), patch.object(self.repository,'latest',AsyncMock(return_value=[fresh])):
            self.assertTrue(await self.repository.canonical_inputs_valid(self.quote,self.instrument))

    async def test_deleted_revoked_stale_or_edited_input_withheld(self):
        for fresh in ([],[SimpleNamespace(id=13)]):
            with patch.object(self.repository,'_input_rows',return_value=self.rows), patch.object(self.repository,'latest',AsyncMock(return_value=fresh)):
                self.assertFalse(await self.repository.canonical_inputs_valid(self.quote,self.instrument))

    async def test_missing_input_or_database_failure_is_not_a_pass(self):
        with patch.object(self.repository,'_input_rows',return_value=[]):
            self.assertFalse(await self.repository.canonical_inputs_valid(self.quote,self.instrument))
        with patch.object(self.repository,'_input_rows',side_effect=TimeoutError):
            self.assertFalse(await self.repository.canonical_inputs_valid(self.quote,self.instrument))

    async def test_missing_verifier_also_withholds_the_cached_quote(self):
        self.quote.verification_quote_ids = [13]
        with patch.object(self.repository,'_input_rows',return_value=self.rows):
            self.assertFalse(await self.repository.canonical_inputs_valid(self.quote,self.instrument))

    async def test_role_or_two_source_requirement_change_withholds_old_cache(self):
        for metadata in ({'source_role':'verifier','source_identity':'one'},
                         {'source_role':'fallback','source_identity':'one','requires_multiple_sources':True}):
            fresh=SimpleNamespace(id=12,provider_id='telegram:1',metadata=metadata)
            with patch.object(self.repository,'_input_rows',return_value=self.rows), patch.object(self.repository,'latest',AsyncMock(return_value=[fresh])):
                self.assertFalse(await self.repository.canonical_inputs_valid(self.quote,self.instrument))

    async def test_both_individual_and_aggregate_read_recheck_cache_inputs(self):
        now = datetime.now(UTC)
        quote = CanonicalQuote(id=1,instrument_id='USDT_TOMAN',price=Decimal(100000),status=CanonicalStatus.LIVE,
            primary_quote_id=12,verification_quote_ids=[],source_summary=summary(),observed_at=now-timedelta(seconds=1),
            canonical_at=now,valid_until=now+timedelta(seconds=30),stale_at=now+timedelta(seconds=60),
            expires_at=now+timedelta(seconds=120),is_persisted=True,decision_reason='owned fixture')
        store,history,operational,telegram = AsyncMock(),AsyncMock(),AsyncMock(),AsyncMock()
        store.get_canonical.return_value=deepcopy(quote)
        history.latest_canonical.return_value=deepcopy(quote)
        store.get_all_canonical.return_value={'USDT_TOMAN':deepcopy(quote)}
        history.latest_all.return_value={'USDT_TOMAN':deepcopy(quote)}
        operational.instrument.return_value=self.instrument
        telegram.canonical_inputs_valid.return_value=False
        service = InstrumentPricingService(store=store,history=history,operational=operational,telegram_quotes=telegram)
        with patch('app.pricing.rights.enforced',return_value=False):
            self.assertIsNone(await service.get_canonical('USDT_TOMAN'))
            self.assertEqual(await service._read_canonical_snapshot({'USDT_TOMAN':self.instrument}),{})
        self.assertGreaterEqual(telegram.canonical_inputs_valid.await_count,2)
