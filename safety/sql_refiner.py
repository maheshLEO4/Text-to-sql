import os
import logging
from typing import Optional, Any
from pydantic import BaseModel
from dotenv import load_dotenv

# Import components from Phase 1 & 2
from safety.query_sandbox import SafeQuerySandbox, ExecutionResult
from safety.guardrails import SQLGuardrailMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [SQL REFINER] - %(message)s")
logger = logging.getLogger("SQLRefiner")


class RefinementResult(BaseModel):
    """Structured response output for SQL auto-healing refinement attempts."""
    final_sql: str
    is_successful: bool
    attempts_taken: int
    execution_result: Optional[ExecutionResult] = None
    last_error: Optional[str] = None


class SQLRefinedEngine:
    """
    Auto-corrects invalid or failing SQL queries by taking execution errors
    and passing them back to the LLM for self-correction retries.
    """

    def __init__(
        self,
        sandbox: Optional[SafeQuerySandbox] = None,
        guardrails: Optional[SQLGuardrailMiddleware] = None,
        db_url: Optional[str] = None,
        llm_client: Any = None,
        max_retries: int = 3,
    ):
        db_url = db_url or os.getenv("DATABASE_URL")
        self.sandbox = sandbox or (SafeQuerySandbox(db_url=db_url) if db_url else None)
        self.guardrails = guardrails or (SQLGuardrailMiddleware(db_url=db_url) if db_url else None)
        self.llm_client = llm_client
        self.max_retries = max_retries

    def _build_refinement_prompt(
        self,
        original_question: str,
        broken_sql: str,
        error_message: str,
        schema_context: str = "",
    ) -> str:
        """Constructs prompt providing feedback on failed SQL execution to LLM."""
        return f"""You are a PostgreSQL expert fixing a failed SQL query.

### ORIGINAL QUESTION:
"{original_question}"

### SCHEMA CONTEXT:
{schema_context if schema_context else "Standard database schema"}

### FAILED SQL QUERY:
```sql
{broken_sql}
```

### DATABASE ERROR ENCOUNTERED:
"{error_message}"

### INSTRUCTIONS:
1. Analyze the database error and identify why the previous SQL statement failed.
2. Fix column names, joins, syntax errors, or data types to resolve the error.
3. Ensure the corrected query strictly answers the original question.
4. Output ONLY the raw executable SQL query without markdown code blocks, preamble, or comments.
"""

    def execute_with_refinement(
        self,
        initial_sql: str,
        user_question: str,
        schema_context: str = "",
        llm_client: Any = None,
    ) -> RefinementResult:
        """
        Executes query inside sandbox. If execution fails, attempts auto-healing refinement loops.
        """
        if self.sandbox is None or self.guardrails is None:
            return RefinementResult(
                final_sql=initial_sql,
                is_successful=False,
                attempts_taken=0,
                last_error="Sandbox or guardrail middleware is not configured. Set DATABASE_URL or pass sandbox/guardrails explicitly.",
            )

        current_sql = initial_sql
        attempt = 1
        error_msg: Optional[str] = None

        while attempt <= self.max_retries:
            logger.info(f"Execution Attempt {attempt}/{self.max_retries} for SQL: '{current_sql[:60]}...'")

            # 1. Run Guardrail Checks
            guardrail_res = self.guardrails.validate_query(current_sql)
            if not guardrail_res.is_safe:
                error_msg = f"Guardrail Violation: {guardrail_res.rejection_reason}"
                logger.warning(f"Attempt {attempt} blocked by guardrail: {error_msg}")

                if attempt == self.max_retries or not llm_client:
                    return RefinementResult(
                        final_sql=current_sql,
                        is_successful=False,
                        attempts_taken=attempt,
                        last_error=error_msg,
                    )
            else:
                # 2. Run inside Query Sandbox
                exec_res = self.sandbox.execute_query(guardrail_res.sanitized_sql)
                if exec_res.success:
                    logger.info(f"Query succeeded on attempt {attempt}!")
                    return RefinementResult(
                        final_sql=guardrail_res.sanitized_sql,
                        is_successful=True,
                        attempts_taken=attempt,
                        execution_result=exec_res,
                    )

                error_msg = exec_res.error_message

            # 3. Handle Retry Logic if LLM is provided
            if attempt < self.max_retries and llm_client:
                refinement_prompt = self._build_refinement_prompt(
                    original_question=user_question,
                    broken_sql=current_sql,
                    error_message=error_msg,
                    schema_context=schema_context,
                )

                logger.info(f"Triggering LLM auto-refinement retry {attempt + 1}...")
                # Reprompt LLM for corrected SQL
                corrected_sql = llm_client.generate(refinement_prompt)
                current_sql = corrected_sql.strip().strip("```sql").strip("```").strip()

            attempt += 1

        return RefinementResult(
            final_sql=current_sql,
            is_successful=False,
            attempts_taken=self.max_retries,
            last_error=error_msg,
        )

    def execute_and_refine(
        self,
        initial_sql: str,
        schema_context: str = "",
        question: str = "",
        llm_client: Any = None,
    ) -> RefinementResult:
        """Compatibility wrapper matching the pipeline's expected method signature."""
        return self.execute_with_refinement(
            initial_sql=initial_sql,
            user_question=question,
            schema_context=schema_context,
            llm_client=llm_client or self.llm_client,
        )

    def refine_sql(
        self,
        question: str,
        initial_sql: str,
        llm_client: Any = None,
        schema_context: str = "",
    ) -> RefinementResult:
        """Backward-compatible wrapper used by the pipeline test harness."""
        return self.execute_with_refinement(
            initial_sql=initial_sql,
            user_question=question,
            schema_context=schema_context,
            llm_client=llm_client,
        )


if __name__ == "__main__":
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL missing in .env")
        exit(1)

    sandbox = SafeQuerySandbox(db_url=db_url)
    guardrails = SQLGuardrailMiddleware(db_url=db_url)
    refiner = SQLRefinedEngine(sandbox=sandbox, guardrails=guardrails, max_retries=2)

    print("--- SQL REFINEMENT ENGINE TESTS ---\n")

    # Mock Execution Test: Intentionally passing broken table name 'non_existent_table'
    broken_query = "SELECT * FROM non_existent_table WHERE id = 1"
    question = "Show details for ID 1"

    res = refiner.execute_with_refinement(
        initial_sql=broken_query,
        user_question=question,
    )

    print(f"\nRefinement Test: Success={res.is_successful} | Attempts={res.attempts_taken} | Error={res.last_error}")