import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from safety.query_sandbox import SafeQuerySandbox


class SQLiteSandboxCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "compat.sqlite"
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE singers (id INTEGER, name TEXT, age INTEGER)")
        conn.execute("INSERT INTO singers (id, name, age) VALUES (1, 'Alice', 30)")
        conn.execute("INSERT INTO singers (id, name, age) VALUES (2, 'Bob', 25)")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sqlite_sandbox_runs_select_without_postgres_statements(self):
        sandbox = SafeQuerySandbox(db_url=f"sqlite:///{self.db_path}", timeout_seconds=5)
        try:
            result = sandbox.execute_query("SELECT name, age FROM singers WHERE age > 20 ORDER BY age DESC")
            self.assertTrue(result.success, msg=result.error_message)
            self.assertEqual(len(result.data), 2)
            self.assertEqual(result.data[0]["name"], "Alice")
        finally:
            sandbox.close()


if __name__ == "__main__":
    unittest.main()
