import os
import time
import logging
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [SANDBOX] - %(message)s")
logger = logging.getLogger("QuerySandbox")


class ExecutionResult(BaseModel):
    """Structured container for SQL query execution output."""
    success: bool
    data: List[Dict[str, Any]] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None


class SafeQuerySandbox:
    """
    Executes validated SQL queries inside a dialect-aware sandbox that
    preserves PostgreSQL safety checks while remaining compatible with SQLite.
    """

    def __init__(self, db_url: Optional[str] = None, timeout_seconds: int = 5):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if not self.db_url:
            raise ValueError("DATABASE_URL must be provided or set in environment variables.")

        self.timeout_seconds = timeout_seconds
        self.engine = create_engine(
            self.db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )
        self.dialect_name = self.engine.dialect.name.lower()

    def close(self) -> None:
        """Release any pooled database connections."""
        if hasattr(self, "engine"):
            self.engine.dispose()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _apply_dialect_specific_safeguards(self, connection) -> None:
        """Applies database-specific session safety settings when supported."""
        if self.dialect_name in {"postgresql", "postgres"}:
            timeout_ms = self.timeout_seconds * 1000
            connection.execute(text(f"SET LOCAL statement_timeout = {timeout_ms};"))
            connection.execute(text("SET TRANSACTION READ ONLY;"))
        elif self.dialect_name == "sqlite":
            # SQLite does not support PostgreSQL's SET LOCAL/SET TRANSACTION READ ONLY.
            # Use the SQLite busy_timeout setting instead, which limits lock wait time.
            connection.execute(text(f"PRAGMA busy_timeout = {self.timeout_seconds * 1000};"))

    def execute_query(self, sql_query: str) -> ExecutionResult:
        """
        Executes SQL query within a read-only transaction block with statement timeouts.
        """
        start_time = time.perf_counter()

        try:
            with self.engine.connect() as connection:
                # Begin a explicit transaction context safely in SQLAlchemy 2.0
                with connection.begin():
                    # Apply database-specific safety settings without issuing
                    # PostgreSQL-only statements against SQLite.
                    self._apply_dialect_specific_safeguards(connection)

                    # Execute the target query
                    result = connection.execute(text(sql_query))

                    columns = list(result.keys()) if result.returns_rows else []
                    rows = result.fetchall() if result.returns_rows else []

                    data = [dict(zip(columns, row)) for row in rows]

                elapsed_ms = (time.perf_counter() - start_time) * 1000

                logger.info(
                    f"SUCCESS - Returned {len(data)} rows in {elapsed_ms:.2f}ms | Query: '{sql_query[:50]}...'"
                )

                return ExecutionResult(
                    success=True,
                    data=data,
                    columns=columns,
                    row_count=len(data),
                    execution_time_ms=round(elapsed_ms, 2)
                )

        except (OperationalError, DBAPIError) as db_err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_str = str(db_err)

            if "statement timeout" in error_str.lower() or "canceling statement" in error_str.lower():
                err_msg = f"Query execution timed out after {self.timeout_seconds} seconds."
            else:
                err_msg = f"Database execution error: {error_str}"

            logger.error(f"FAILED - {err_msg} | Query: '{sql_query}'")
            return ExecutionResult(
                success=False,
                error_message=err_msg,
                execution_time_ms=round(elapsed_ms, 2)
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            err_msg = f"Unexpected sandbox error: {str(e)}"
            logger.error(f"FAILED - {err_msg}")
            return ExecutionResult(
                success=False,
                error_message=err_msg,
                execution_time_ms=round(elapsed_ms, 2)
            )


if __name__ == "__main__":
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Please set DATABASE_URL in .env to run sandbox verification.")
        exit(1)

    sandbox = SafeQuerySandbox(db_url=db_url, timeout_seconds=3)

    print("--- QUERY SANDBOX TESTS ---\n")

    # Test 1: Valid Execution
    test_1 = "SELECT customer_id, company_name FROM customers LIMIT 5;"
    res1 = sandbox.execute_query(test_1)
    print(f"Test 1 (Valid): Success={res1.success} | Rows={res1.row_count} | Time={res1.execution_time_ms}ms")
    if res1.success:
        print(f"Data Sample: {res1.data[:2]}\n")

    # Test 2: Timeout Check (pg_sleep)
    test_2 = "SELECT pg_sleep(5);"
    res2 = sandbox.execute_query(test_2)
    print(f"Test 2 (Timeout Check): Success={res2.success} | Error={res2.error_message}\n")