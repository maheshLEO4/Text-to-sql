import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

load_dotenv(override=True)


def get_model_name(model_name: str | None = None) -> str:
    """Resolve the Groq model from .env or fall back to a valid default."""
    return (model_name or os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant").strip()


class BacktranslationVerificationResult(BaseModel):
    backtranslated_question: str = Field(
        ..., 
        description="The plain-English question that the given SQL query actually answers."
    )
    alignment_score: float = Field(
        ..., 
        description="Score between 0.0 and 1.0 indicating how closely the backtranslated question matches the original intent."
    )
    alignment_reasoning: str = Field(
        ..., 
        description="Explanation of why the backtranslated question matches or diverges from the original user question."
    )
    is_aligned: bool = Field(
        ..., 
        description="True if alignment_score >= 0.70, indicating high semantic match."
    )


class BacktranslationVerifier:
    """
    Performs backtranslation verification: translates generated SQL back into 
    natural language and evaluates semantic alignment with the original question.
    """

    def __init__(self, model_name: Optional[str] = None, api_key: Optional[str] = None):
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is missing.")

        resolved_model_name = get_model_name(model_name)

        base_llm = ChatGroq(
            temperature=0.0,
            model=resolved_model_name,
            groq_api_key=api_key,
        )
        self.structured_llm = base_llm.with_structured_output(BacktranslationVerificationResult)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are an expert SQL Auditor and Data QA Specialist.\n"
             "Your job is to inspect a generated SQL query, explain in plain English what question it ACTUALLY answers, "
             "and compare it to the original user intent.\n\n"
             "Rules:\n"
             "1. Do not assume intent beyond what the SQL strictly computes.\n"
             "2. Identify mismatched filters, wrong aggregations, or missing JOIN tables.\n"
             "3. Provide an alignment_score between 0.0 (completely different question) and 1.0 (exact match).\n"
             "4. Set is_aligned to True ONLY if alignment_score >= 0.70."
            ),
            ("user", 
             "Original User Question: {original_question}\n\n"
             "Generated SQL Query:\n```sql\n{generated_sql}\n```\n\n"
             "Perform backtranslation and evaluate alignment."
            )
        ])

    def verify_query(self, original_question: str, generated_sql: str) -> BacktranslationVerificationResult:
        """Executes backtranslation and returns structured evaluation result."""
        chain = self.prompt | self.structured_llm
        try:
            raw_result = chain.invoke({
                "original_question": original_question,
                "generated_sql": generated_sql
            })
            if not raw_result:
                raise ValueError("Failed to retrieve structured backtranslation output.")

            # LangChain/Groq can return a dict despite the Pydantic schema.
            # Normalize it here so confidence scoring can use model attributes.
            result = (
                raw_result
                if isinstance(raw_result, BacktranslationVerificationResult)
                else BacktranslationVerificationResult.model_validate(raw_result)
            )
            return result
        except Exception as e:
            return BacktranslationVerificationResult(
                backtranslated_question="Failed to backtranslate query.",
                alignment_score=0.0,
                alignment_reasoning=f"Backtranslation error: {str(e)}",
                is_aligned=False
            )

    def verify_hallucination(self, original_question: str, generated_sql: str, schema_context: str = "") -> BacktranslationVerificationResult:
        """Compatibility wrapper used by the pipeline harness."""
        return self.verify_query(original_question, generated_sql)


class SQLBacktranslator(BacktranslationVerifier):
    """Backward compatible alias for the original engine name."""
    pass


# -----------------------------------------------------------------------------
# Quick Standalone Test Driver
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    verifier = SQLBacktranslator()

    # Test Case 1: Aligned Query
    user_q1 = "Show the top 5 customers who spent the most money"
    sql_1 = "SELECT customer_id, SUM(unit_price * quantity) AS total_spent FROM orders GROUP BY customer_id ORDER BY total_spent DESC LIMIT 5;"
    
    print("--- Test 1: High Alignment ---")
    res1 = verifier.verify_query(user_q1, sql_1)
    print(json.dumps(res1.model_dump(), indent=2))

    # Test Case 2: Divergent Query (Hallucinated logic)
    user_q2 = "List customers who ordered products in 1997"
    sql_2 = "SELECT * FROM products WHERE units_in_stock > 100;"
    
    print("\n--- Test 2: Low Alignment (Hallucinated/Mismatched SQL) ---")
    res2 = verifier.verify_query(user_q2, sql_2)
    print(json.dumps(res2.model_dump(), indent=2))