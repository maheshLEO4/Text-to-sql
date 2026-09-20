import os
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

load_dotenv(override=True)


def get_model_name(model_name: str | None = None) -> str:
    """Resolve the Groq model from .env or fall back to a valid default."""
    return (model_name or os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()


class MultiQueryVariantResponse(BaseModel):
    query_variant_1: str = Field(
        ..., 
        description="First SQL query approach (standard JOIN/aggregation path)."
    )
    query_variant_2: str = Field(
        ..., 
        description="Alternative independent SQL query approach (e.g. using CTE, subqueries, or distinct grouping)."
    )
    strategy_difference: str = Field(
        ..., 
        description="Brief description explaining how the two query approaches differ in strategy."
    )


class ConsensusValidationResult(BaseModel):
    is_consensus_reached: bool = Field(
        ..., 
        description="True if both SQL executions yielded identical result sets or aggregated values."
    )
    agreement_score: float = Field(
        ..., 
        description="Score between 0.0 and 1.0 representing result set agreement level."
    )
    variant_1_sql: str
    variant_2_sql: str
    variance_details: Optional[str] = Field(
        None, 
        description="Details on divergence if consensus was not reached."
    )


class MultiQueryValidator:
    """
    Generates two independent SQL query strategies and compares their 
    executed output to verify correctness through consensus.
    """

    def __init__(self, model_name: Optional[str] = None, api_key: Optional[str] = None):
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is missing.")

        resolved_model_name = get_model_name(model_name)

        base_llm = ChatGroq(
            temperature=0.2,
            model=resolved_model_name,
            groq_api_key=api_key,
        )
        self.structured_llm = base_llm.with_structured_output(MultiQueryVariantResponse)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a PostgreSQL expert.\n"
             "Your job is to generate TWO DISTINCT, syntactically valid PostgreSQL queries to answer the user's question.\n"
             "Variant 1 should use standard JOINs and direct logic.\n"
             "Variant 2 should use an alternative strategy (e.g. CTEs, subqueries, or distinct GROUP BY techniques).\n"
             "Both must target the provided database schema context accurately."
            ),
            ("user",
             "Database Schema Context:\n{schema_context}\n\n"
             "User Question: {question}"
            )
        ])

    def generate_variants(self, question: str, schema_context: str) -> MultiQueryVariantResponse:
        """
        Generates two distinct candidate SQL queries.
        """
        chain = self.prompt | self.structured_llm
        return chain.invoke({"question": question, "schema_context": schema_context})

    def evaluate_consensus(
        self, 
        sql_1: str, 
        data_1: List[Dict[str, Any]], 
        sql_2: str, 
        data_2: List[Dict[str, Any]]
    ) -> ConsensusValidationResult:
        """
        Compares execution results from both query variants to verify data consensus.
        """
        # Convert list of dicts to sorted normalized representations for deterministic comparison
        try:
            # Sort keys in dicts to standardize comparison
            norm_1 = [dict(sorted(row.items())) for row in data_1]
            norm_2 = [dict(sorted(row.items())) for row in data_2]

            # Direct row count check
            if len(norm_1) != len(norm_2):
                return ConsensusValidationResult(
                    is_consensus_reached=False,
                    agreement_score=0.5,
                    variant_1_sql=sql_1,
                    variant_2_sql=sql_2,
                    variance_details=f"Row count mismatch: Variant 1 returned {len(norm_1)} rows, Variant 2 returned {len(norm_2)} rows."
                )

            # Direct content comparison
            if norm_1 == norm_2:
                return ConsensusValidationResult(
                    is_consensus_reached=True,
                    agreement_score=1.0,
                    variant_1_sql=sql_1,
                    variant_2_sql=sql_2,
                    variance_details="Exact consensus: Both execution results match perfectly."
                )
            else:
                return ConsensusValidationResult(
                    is_consensus_reached=False,
                    agreement_score=0.7,
                    variant_1_sql=sql_1,
                    variant_2_sql=sql_2,
                    variance_details="Data content divergence: Row counts match, but value contents differ between query variants."
                )

        except Exception as e:
            return ConsensusValidationResult(
                is_consensus_reached=False,
                agreement_score=0.0,
                variant_1_sql=sql_1,
                variant_2_sql=sql_2,
                variance_details=f"Evaluation error: {str(e)}"
            )


# -----------------------------------------------------------------------------
# Quick Standalone Test Driver
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    validator = MultiQueryValidator()

    # Test Consensus Comparison
    data_a = [{"product_id": 1, "total": 100}, {"product_id": 2, "total": 200}]
    data_b = [{"product_id": 1, "total": 100}, {"product_id": 2, "total": 200}]
    data_c = [{"product_id": 1, "total": 100}]

    print("--- Test 1: Matching Outputs ---")
    res1 = validator.evaluate_consensus("SELECT 1", data_a, "SELECT 2", data_b)
    print(json.dumps(res1.model_dump(), indent=2))

    print("\n--- Test 2: Divergent Row Counts ---")
    res2 = validator.evaluate_consensus("SELECT 1", data_a, "SELECT 2", data_c)
    print(json.dumps(res2.model_dump(), indent=2))
