from __future__ import annotations

import os
import inspect
import unittest

os.environ.setdefault("JWT_SECRET_KEY", "database-contract-test-key-not-for-runtime-000000")

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url
import asyncpg

from app.db import _async_connect_args, _async_database_url


class DatabaseConnectionOptionTests(unittest.TestCase):
    def test_async_driver_preserves_tls_and_server_options_without_opening_socket(self):
        source = "postgresql+psycopg://test_user:test@db.example.test/test_db?sslmode=verify-full&sslrootcert=ca.pem&sslcert=client.pem&sslkey=client.key&application_name=contract-test&options=-csearch_path%3Dfixture"
        engine = create_async_engine(_async_database_url(source), connect_args=_async_connect_args(source))
        self.assertTrue(engine.dialect.is_async)
        self.assertEqual(engine.dialect.driver, "asyncpg")
        _args, options = engine.dialect.create_connect_args(engine.url)
        connect = _async_connect_args(source)
        inspect.signature(asyncpg.connect).bind(*_args, **{**options, **connect})
        dsn_options = make_url(connect["dsn"]).query
        self.assertEqual(dsn_options["sslmode"], "verify-full")
        self.assertEqual(dsn_options["sslrootcert"], "ca.pem")
        self.assertEqual(dsn_options["sslcert"], "client.pem")
        self.assertEqual(dsn_options["sslkey"], "client.key")
        self.assertEqual(dsn_options["application_name"], "contract-test")
        self.assertEqual(dsn_options["options"], "-csearch_path=fixture")
        self.assertEqual(connect["timeout"], 5)
        self.assertEqual(connect["command_timeout"], 15)
        self.assertNotIn("sslmode", connect)

    def test_plain_postgres_and_sqlite_urls_keep_their_expected_driver(self):
        self.assertEqual(_async_database_url("postgresql://test@localhost/test_db?sslmode=require"), "postgresql+asyncpg://test@localhost/test_db")
        self.assertEqual(_async_database_url("sqlite+aiosqlite:///test.db"), "sqlite+aiosqlite:///test.db")
        self.assertEqual(_async_connect_args("sqlite+aiosqlite:///test.db"), {})


if __name__ == "__main__":
    unittest.main()
