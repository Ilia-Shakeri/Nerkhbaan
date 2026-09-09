from __future__ import annotations

import json
import logging
import unittest

from prometheus_client import generate_latest

from app.observability import (
    JsonFormatter,
    alert_delivery_total,
    request_id_context,
    set_canonical_status,
    set_queue_depths,
)


class ObservabilityTests(unittest.TestCase):
    def test_json_log_contains_request_and_typed_fields(self) -> None:
        token = request_id_context.set("request-123")
        try:
            record = logging.LogRecord(
                "test.logger", logging.ERROR, __file__, 1, "failed %s", ("once",), None
            )
            record.instrument_id = "BTC_USD"
            record.error_type = "TimeoutError"
            payload = json.loads(JsonFormatter().format(record))
        finally:
            request_id_context.reset(token)
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["instrument_id"], "BTC_USD")
        self.assertEqual(payload["error_type"], "TimeoutError")
        self.assertEqual(payload["message"], "failed once")

    def test_operational_metrics_are_exposed(self) -> None:
        set_canonical_status("BTC_USD", "live")
        set_queue_depths({"dead_letters": 2})
        alert_delivery_total.labels(channel="push", status="delivered").inc()
        output = generate_latest().decode("utf-8")
        self.assertIn('nerkhbaan_canonical_status{instrument="BTC_USD",status="live"} 1.0', output)
        self.assertIn('nerkhbaan_queue_depth{queue="dead_letters"} 2.0', output)
        self.assertIn('nerkhbaan_alert_delivery_total{channel="push",status="delivered"}', output)


if __name__ == "__main__":
    unittest.main()
