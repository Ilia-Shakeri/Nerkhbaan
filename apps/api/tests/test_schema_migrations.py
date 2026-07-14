import unittest

from app.schema_migrations import apply_schema_migrations


class _Connection:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))


class _Transaction:
    def __init__(self, connection: _Connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Engine:
    def __init__(self):
        self.connection = _Connection()

    def begin(self):
        return _Transaction(self.connection)


class SchemaMigrationTests(unittest.TestCase):
    def test_alert_migration_adds_all_runtime_columns(self):
        engine = _Engine()

        apply_schema_migrations(engine)  # type: ignore[arg-type]

        sql = engine.connection.statements[0]
        for column in (
            'alert_type',
            'formula',
            'currency_mode',
            'notify_webhook',
            'webhook_url',
            'enable_dlq',
        ):
            self.assertIn(f'ADD COLUMN IF NOT EXISTS {column}', sql)
        self.assertIn('ALTER COLUMN target_price DROP NOT NULL', sql)


if __name__ == '__main__':
    unittest.main()
