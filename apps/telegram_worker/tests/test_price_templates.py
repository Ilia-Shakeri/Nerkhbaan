"""Explicit supported templates; unsafe units and ambiguous prices stay rejected."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from apps.telegram_worker.app.parser import RULES, parse_message


class PriceTemplateTests(unittest.TestCase):
    def parse(self, text):
        return parse_message(text, allowed_instruments={rule.instrument_id for rule in RULES},
                             parser_type='strict_explicit',minimum_confidence=Decimal('.8'))

    def test_every_native_instrument_has_an_explicit_safe_template(self):
        cases = [
            ('طلای ۱۸ عیار هر گرم ۹۰۰۰۰۰۰ تومان','GOLD_18K_TOMAN_GRAM','9000000'),
            ('طلای 24 عیار خلوص 9999 هر گرم 13000000 تومان','GOLD_24K_TOMAN_GRAM','13000000'),
            ('نقره 999 هر گرم 150000 تومان','SILVER_999_TOMAN_GRAM','150000'),
            ('نقره 925 هر گرم 140000 تومان','SILVER_925_TOMAN_GRAM','140000'),
            ('USD 100000 تومان','USD_TOMAN','100000'),
            ('USDT 100000 تومان','USDT_TOMAN','100000'),
            ('BTC 10000000000 تومان','BTC_TOMAN','10000000000'),
            ('XAUUSD 4000 USD oz','XAU_USD_OZ','4000'),
            ('XAGUSD 45 USD oz','XAG_USD_OZ','45'),
            ('BTC/USD 100000 USD','BTC_USD','100000'),
            ('USDT/USD 1.0001 USD','USDT_USD','1.0001'),
        ]
        for text, instrument, price in cases:
            with self.subTest(instrument=instrument):
                accepted=[quote for quote in self.parse(text) if quote.validation_status=='accepted']
                self.assertEqual([(quote.instrument_id,quote.price) for quote in accepted],[(instrument,Decimal(price))])

    def test_unsafe_numbers_units_or_unproved_purity_never_become_quotes(self):
        for text in ('USDT -100000 تومان','USDT −100000 تومان','USDT 100,00 تومان',
                     'USDT 100000,50 تومان','USDT 100000 تومان ریال',
                     'طلای 18 عیار هر کیلوگرم 9000000 تومان',
                     'طلای 24 عیار هر گرم 13000000 تومان',
                     'XAUUSD هر گرم 4000 USD','XAGUSD 45 USD',
                     'USDT 100000 101000 تومان'):
            with self.subTest(text=text):
                self.assertFalse(any(quote.validation_status=='accepted' for quote in self.parse(text)))

    def test_dollar_label_does_not_match_tether(self):
        for text in ('USDT 100000 تومان','نرخ دلار تتر 100000 تومان'):
            self.assertFalse(any(q.instrument_id=='USD_TOMAN' and q.validation_status=='accepted' for q in self.parse(text)))

    def test_oversize_text_is_not_silently_truncated_into_a_valid_price(self):
        result=self.parse('USDT 100000 تومان\n'+'x'*4000+'\nUSDT 101000 تومان')
        self.assertEqual(result[0].rejection_reason,'message_too_long')
