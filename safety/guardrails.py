import logging
import re
import sqlparse
from sqlparse.sql import Parenthesis, Statement
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel
from sqlalchemy import create_engine, text

# Audit Logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [GUARDRAIL AUDIT] - %(message)s")
logger = logging.getLogger("GuardrailMiddleware")


class GuardrailConfig(BaseModel):
    """Configurable threshold rules for SQL execution safety."""
    max_row_limit: int = 1000
    max_subquery_depth: int = 3
    max_estimated_rows_scanned: int = 100_000
    max_explain_cost: float = 10_000.0


class GuardrailValidationResult(BaseModel):
    """Response returned by the guardrail check."""
    is_safe: bool
    sanitized_sql: str
    rejection_reason: Optional[str] = None
    estimated_cost: Optional[float] = None
    estimated_rows: Optional[int] = None


class SQLGuardrailMiddleware:
    """
    Pre-execution safety middleware that intercepts generated SQL queries,
    validates rules, enforces constraints, and runs EXPLAIN checks.
    """

    FORBIDDEN_KEYWORDS = {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", 
        "TRUNCATE", "GRANT", "REVOKE", "VACUUM", "COPY", "REINDEX",
        "EXEC", "EXECUTE", "MERGE"
    }

    def __init__(self, db_url: Optional[str] = None, config: Optional[GuardrailConfig] = None):
        self.config = config or GuardrailConfig()
        self.engine = create_engine(db_url, pool_pre_ping=True) if db_url else None
        # Dialect drives how (or whether) we can run a cost-estimation EXPLAIN:
        # Postgres supports "EXPLAIN (FORMAT JSON) ..." with real cost/row
        # estimates; SQLite has no equivalent syntax or cost model.
        self.dialect_name = self.engine.dialect.name if self.engine else None

    def check_forbidden_statements(self, sql_query: str) -> Tuple[bool, Optional[str]]:
        """Rule 1: Blocks DDL and DML write/destructive commands."""
        parsed = sqlparse.parse(sql_query)
        for statement in parsed:
            stmt_type = statement.get_type()
            if stmt_type != "SELECT" and stmt_type != "UNKNOWN":
                return False, f"Forbidden SQL statement type: '{stmt_type}'. Only SELECT statements are permitted."

            for token in statement.flatten():
                token_val = token.value.upper()
                if token_val in self.FORBIDDEN_KEYWORDS:
                    return False, f"Forbidden keyword detected: '{token_val}'."

        return True, None

    def enforce_row_limit(self, sql_query: str) -> str:
        """Rule 2: Enforces LIMIT clauses to avoid massive result set fetches."""
        limit_match = re.search(r"\bLIMIT\s+(\d+)", sql_query, re.IGNORECASE)
        
        if limit_match:
            existing_limit = int(limit_match.group(1))
            if existing_limit > self.config.max_row_limit:
                sql_query = re.sub(
                    r"\bLIMIT\s+\d+", 
                    f"LIMIT {self.config.max_row_limit}", 
                    sql_query, 
                    flags=re.IGNORECASE
                )
        else:
            sql_query = f"{sql_query.strip()} LIMIT {self.config.max_row_limit}"

        return sql_query

    def calculate_subquery_depth(self, token_node, current_depth: int = 0) -> int:
        """Recursively calculates maximum subquery nesting depth."""
        max_depth = current_depth
        if hasattr(token_node, 'tokens'):
            for item in token_node.tokens:
                if isinstance(item, Parenthesis):
                    inner_str = item.value.upper()
                    if "SELECT" in inner_str:
                        sub_depth = self.calculate_subquery_depth(item, current_depth + 1)
                        max_depth = max(max_depth, sub_depth)
                elif item.is_group:
                    max_depth = max(max_depth, self.calculate_subquery_depth(item, current_depth))
        return max_depth

    def check_subquery_depth(self, sql_query: str) -> Tuple[bool, Optional[str]]:
        """Rule 3: Blocks subquery nesting deeper than allowed threshold."""
        parsed = sqlparse.parse(sql_query)
        if not parsed:
            return True, None

        # Subtract 1 for outer SELECT statement body check
        depth = self.calculate_subquery_depth(parsed[0], current_depth=0)
        if depth > self.config.max_subquery_depth:
            return False, f"Subquery nesting depth ({depth}) exceeds maximum allowed depth ({self.config.max_subquery_depth})."

        return True, None
    
    def check_explain_cost(self, sql_query: str) -> Tuple[bool, Optional[str], Optional[float], Optional[int]]:
        """Rule 4: Runs an EXPLAIN-based check to estimate predicted cost and rows.

        This is dialect-dependent: Postgres/Supabase supports
        "EXPLAIN (FORMAT JSON) ..." with real cost and row estimates, which we
        use to enforce max_estimated_rows_scanned / max_explain_cost.

        SQLite has no equivalent JSON cost model and doesn't accept that
        syntax at all (it errors with a plain SQL syntax error), so there is
        no reliable, comparable cost figure to enforce there. Rather than
        treat every query as unsafe due to a syntax mismatch, we skip the
        cost/row estimation step for SQLite (and any other non-Postgres
        dialect) and rely on Rules 1-3 (forbidden statements, row LIMIT
        enforcement, subquery depth) for safety on those engines.
        """
        if not self.engine:
            return True, None, None, None

        if self.dialect_name not in ("postgresql", "postgres"):
            # No comparable EXPLAIN/cost model for this dialect (e.g. SQLite).
            return True, None, None, None

        explain_sql = f"EXPLAIN (FORMAT JSON) {sql_query}"
        try:
            with self.engine.connect() as conn:
                res = conn.execute(text(explain_sql)).scalar()
                
                plan = res[0]["Plan"]
                total_cost = float(plan.get("Total Cost", 0.0))
                plan_rows = int(plan.get("Plan Rows", 0))

                if plan_rows > self.config.max_estimated_rows_scanned:
                    return (
                        False, 
                        f"Estimated rows scanned ({plan_rows:,}) exceeds limit ({self.config.max_estimated_rows_scanned:,}).", 
                        total_cost, 
                        plan_rows
                    )

                if total_cost > self.config.max_explain_cost:
                    return (
                        False, 
                        f"Estimated execution cost ({total_cost:,.2f}) exceeds max allowed cost ({self.config.max_explain_cost:,.2f}).", 
                        total_cost, 
                        plan_rows
                    )

                return True, None, total_cost, plan_rows

        except Exception as e:
            return False, f"EXPLAIN validation failed: {str(e)}", None, None

    def validate_query(self, raw_sql: str) -> GuardrailValidationResult:
        """Executes all guardrail safety rules in sequence."""
        sql = raw_sql.strip().rstrip(";")

        # Rule 1: DDL/DML Block
        is_safe, reason = self.check_forbidden_statements(sql)
        if not is_safe:
            logger.warning(f"BLOCKED - Write Operation: {reason} | SQL: '{sql}'")
            return GuardrailValidationResult(is_safe=False, sanitized_sql=sql, rejection_reason=reason)

        # Rule 2: Enforce row limit
        sanitized_sql = self.enforce_row_limit(sql)

        # Rule 3: Subquery depth AST check (Evaluated BEFORE database EXPLAIN call)
        is_safe, reason = self.check_subquery_depth(sanitized_sql)
        if not is_safe:
            logger.warning(f"BLOCKED - Subquery Depth: {reason} | SQL: '{sanitized_sql}'")
            return GuardrailValidationResult(is_safe=False, sanitized_sql=sanitized_sql, rejection_reason=reason)

        # Rule 4: DB EXPLAIN Cost estimation check
        is_safe, reason, cost, rows = self.check_explain_cost(sanitized_sql)
        if not is_safe:
            logger.warning(f"BLOCKED - Query Cost/Rows Exceeded: {reason} | SQL: '{sanitized_sql}'")
            return GuardrailValidationResult(
                is_safe=False, 
                sanitized_sql=sanitized_sql, 
                rejection_reason=reason,
                estimated_cost=cost,
                estimated_rows=rows
            )

        logger.info(f"PASSED - SQL: '{sanitized_sql}' | Estimated Cost: {cost} | Estimated Rows: {rows}")
        return GuardrailValidationResult(
            is_safe=True, 
            sanitized_sql=sanitized_sql, 
            estimated_cost=cost, 
            estimated_rows=rows
        )

    def validate_and_sanitize(self, raw_sql: str) -> GuardrailValidationResult:
        """Compatibility wrapper for the pipeline harness."""
        return self.validate_query(raw_sql)


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    db_url = os.getenv("DATABASE_URL")
    guardrail = SQLGuardrailMiddleware(db_url=db_url)

    print("--- GUARDRAIL MIDDLEWARE TESTS ---\n")

    # Test 1: Destructive Query
    test_1 = "DROP TABLE customers;"
    res1 = guardrail.validate_query(test_1)
    print(f"Test 1 (DROP): Safe={res1.is_safe} | Reason={res1.rejection_reason}\n")

    # Test 2: Row limit enforcement
    test_2 = "SELECT * FROM orders"
    res2 = guardrail.validate_query(test_2)
    print(f"Test 2 (No LIMIT): Safe={res2.is_safe} | Sanitized SQL='{res2.sanitized_sql}'\n")

    # Test 3: Deeply nested subquery (> 3 levels) using valid Northwind tables
    test_3 = """
    SELECT * FROM orders WHERE order_id IN (
        SELECT order_id FROM order_details WHERE product_id IN (
            SELECT product_id FROM products WHERE category_id IN (
                SELECT category_id FROM categories WHERE category_name IN (
                    SELECT category_name FROM categories
                )
            )
        )
    )
    """
    res3 = guardrail.validate_query(test_3)
    print(f"Test 3 (Deep Subquery): Safe={res3.is_safe} | Reason={res3.rejection_reason}\n")

    # Test 4: Valid SELECT query
    test_4 = "SELECT customer_id, count(*) FROM customers GROUP BY customer_id"
    res4 = guardrail.validate_query(test_4)
    print(f"Test 4 (Valid SELECT): Safe={res4.is_safe} | Cost={res4.estimated_cost} | Rows={res4.estimated_rows}")