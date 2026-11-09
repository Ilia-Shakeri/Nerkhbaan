"""Administrator table reads must fit inside the request's existing connection."""
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.admin.dbtools import _reflected, reflected_table, safe_count


class AdminReflectionPoolTests(unittest.TestCase):
    def test_internal_error_remains_readable_only_for_allowed_browser_origins(self):
        from fastapi import Request
        from app.main import global_exception_handler
        for origin in ("https://web.example", "https://admin.example", "https://foreign.example", None):
            with self.subTest(origin=origin):
                request = Request({"type": "http", "method": "GET", "path": "/api/admin/auth/csrf",
                                   "headers": [(b"origin", origin.encode())] if origin else []})
                with patch("app.main.origins", ["https://web.example", "https://admin.example"]), patch("app.main.logger"):
                    response = asyncio.run(global_exception_handler(request, RuntimeError("private failure details")))
                self.assertEqual(response.status_code, 500)
                self.assertNotIn(b"private failure details", response.body)
                self.assertIn("request_id", response.body.decode())
                if origin in ("https://web.example", "https://admin.example"):
                    self.assertEqual(response.headers["access-control-allow-origin"], origin)
                    self.assertEqual(response.headers["access-control-allow-credentials"], "true")
                    self.assertEqual(response.headers["vary"], "Origin")
                else:
                    self.assertNotIn("access-control-allow-origin", response.headers)

    def test_cold_reflection_reuses_the_only_checked_out_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'admin-test.db'}", poolclass=QueuePool,
                                   pool_size=1, max_overflow=0, pool_timeout=0.1)
            try:
                with engine.begin() as connection:
                    connection.execute(text("CREATE TABLE review_rows (id INTEGER PRIMARY KEY, status TEXT)"))
                    connection.execute(text("INSERT INTO review_rows VALUES (1, 'open')"))
                with Session(engine) as db:
                    db.execute(text("SELECT 1"))
                    self.assertEqual(engine.pool.checkedout(), 1)
                    table = reflected_table(db, "review_rows")
                    self.assertIsNotNone(table)
                    self.assertEqual(safe_count(db, "review_rows"), 1)
                    self.assertIs(reflected_table(db, "review_rows"), table)
                    self.assertIsNone(reflected_table(db, "absent_table"))
                    self.assertEqual(engine.pool.checkedout(), 1)
                self.assertEqual(engine.pool.checkedout(), 0)
            finally:
                for key in list(_reflected):
                    if key[0] is engine:
                        _reflected.pop(key)
                engine.dispose()
