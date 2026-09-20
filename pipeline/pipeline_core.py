"""
pipeline_core.py

The single source of truth for running a natural-language question through
the full Text-to-SQL pipeline (schema -> ambiguity -> generation -> guardrails
-> execution -> verification -> confidence scoring).

This module returns STRUCTURED data (a PipelineResult) instead of printing,
so it can be reused by:
  - the CLI harness (test_pipeline.py)
  - the FastAPI service (api/main.py)
  - the future eval suite (Phase 5)

Keeping this logic in one place avoids the CLI and the API silently drifting
apart as the pipeline evolves.
"""

import os
import re
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Make sibling package folders importable regardless of where this file is run from
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_THIS_DIR)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from ingestion.schema_extractor import SchemaExtractor
from ingestion.schema_filter import SchemaFilter
from generation.prompt_constructor import PromptConstructor, FewShotExample
from generation.ambiguity_handler import DynamicAmbiguityHandler, AmbiguityCheckResult
from generation.sql_generator import SQLGenerator
from generation.llm_client import SQLGeneratorPipeline
from pipeline.feedback_store import FeedbackStore

from safety.guardrails import SQLGuardrailMiddleware
from safety.query_sandbox import SafeQuerySandbox
from safety.sql_refiner import SQLRefinedEngine

from verification.hallucination_detector import BacktranslationVerifier
from verification.result_sanity_checker import ResultSanityChecker
from verification.multi_query_validator import MultiQueryValidator
from verification.confidence_scorer import ConfidenceScoringEngine, OverallConfidenceReport

load_dotenv()


class PipelineResult(BaseModel):
    """Structured, API-friendly result of running one question through the pipeline."""

    status: str = Field(
        ...,
        description="One of: SUCCESS, AMBIGUOUS, GUARDRAIL_BLOCKED, EXECUTION_FAILED, CONFIG_ERROR."
    )
    question: str
    generated_sql: Optional[str] = None
    explanation: Optional[str] = None
    natural_language_answer: Optional[str] = None
    data: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    confidence_report: Optional[OverallConfidenceReport] = None
    ambiguity: Optional[AmbiguityCheckResult] = None
    guardrail_rejection_reason: Optional[str] = None
    error_message: Optional[str] = None
    filtered_tables: List[str] = Field(default_factory=list)
    constructed_prompt: Optional[str] = None
    few_shots_count: int = 0


def detect_destructive_request(user_question: str) -> Optional[str]:
    """Detect SQL write/DDL commands before schema or LLM processing."""
    patterns = (
        r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA|VIEW|INDEX)\b",
        r"\bDELETE\s+FROM\b",
        r"\bUPDATE\s+[\w\".]+\s+SET\b",
        r"\bINSERT\s+INTO\b",
        r"\bALTER\s+(?:TABLE|DATABASE|SCHEMA)\b",
        r"\bTRUNCATE(?:\s+TABLE)?\b",
        r"\bCREATE\s+(?:TABLE|DATABASE|SCHEMA|VIEW|INDEX)\b",
        r"\b(?:GRANT|REVOKE|VACUUM|REINDEX)\b",
        r"\b(?:DELETE|DROP|REMOVE|DESTROY|TRUNCATE)\s+(?:ALL\s+)?(?:THE\s+)?[\w\".]+\b",
    )

    for pattern in patterns:
        match = re.search(pattern, user_question, flags=re.IGNORECASE)
        if match:
            return f"Destructive SQL command detected: '{match.group(0)}'."
    return None


def run_pipeline(user_question: str, db_url: Optional[str] = None) -> PipelineResult:
    """
    Runs the full Text-to-SQL pipeline for a single question and returns a
    structured PipelineResult. Never raises for expected failure modes
    (ambiguity, guardrail block, execution failure) — those are reported
    via `status` instead, so callers (API, CLI, evals) can branch on it
    without wrapping every call in try/except.
    """
    destructive_reason = detect_destructive_request(user_question)
    if destructive_reason:
        return PipelineResult(
            status="GUARDRAIL_BLOCKED",
            question=user_question,
            guardrail_rejection_reason=destructive_reason,
        )

    db_url = db_url or os.getenv("DATABASE_URL")
    if not db_url:
        return PipelineResult(
            status="CONFIG_ERROR",
            question=user_question,
            error_message="DATABASE_URL is not set in environment variables.",
        )

    # --- STEP 1: Schema Extraction & RAG Filtering ---
    extractor = SchemaExtractor(db_url)
    full_schema = extractor.extract_full_schema()

    schema_filter = SchemaFilter(full_schema)
    filtered_schema = schema_filter.filter_schema(user_question, top_k=5)
    formatted_schema = schema_filter.format_for_prompt(filtered_schema)
    filtered_tables = list(filtered_schema.keys())

    # --- STEP 2: Ambiguity Analysis ---
    ambiguity_handler = DynamicAmbiguityHandler()
    ambiguity_res = ambiguity_handler.check_ambiguity_mock(user_question)

    if ambiguity_res.is_ambiguous:
        return PipelineResult(
            status="AMBIGUOUS",
            question=user_question,
            ambiguity=ambiguity_res,
            filtered_tables=filtered_tables,
        )

    # --- STEP 3: Prompt Construction & SQL Generation ---
    feedback_store = FeedbackStore()
    feedback_examples = feedback_store.export_few_shot_for_prompting(top_k=5)
    few_shots = [
        FewShotExample(
            question=item["question"],
            sql=item["sql"],
            explanation=item.get("answer") or item.get("explanation") or "",
            category=item.get("category") or "",
            usage_count=int(item.get("usage_count") or 0),
        )
        for item in feedback_examples
    ]

    prompt_builder = PromptConstructor(dialect="PostgreSQL", few_shots=few_shots)
    system_prompt_str = prompt_builder.build_system_prompt(formatted_schema)
    user_prompt_str = prompt_builder.build_user_prompt(user_question)

    full_constructed_prompt = f"=== SYSTEM PROMPT ===\n{system_prompt_str}\n\n=== USER PROMPT ===\n{user_prompt_str}"

    print("\n" + "=" * 80)
    print(f"📌 [CONSTRUCTED PROMPT FOR USER QUESTION - {len(few_shots)} FEW-SHOT EXAMPLES INCLUDED]")
    print("=" * 80)
    print(full_constructed_prompt)
    print("=" * 80 + "\n")

    sql_gen = SQLGenerator()
    gen_result = sql_gen.generate_sql(
        question=user_question,
        formatted_schema=formatted_schema,
        few_shots=few_shots,
    )

    # --- STEP 4: Guardrail Validation ---
    middleware = SQLGuardrailMiddleware(db_url=db_url)
    guardrail_res = middleware.validate_and_sanitize(gen_result.sql)

    if not guardrail_res.is_safe:
        return PipelineResult(
            status="GUARDRAIL_BLOCKED",
            question=user_question,
            generated_sql=gen_result.sql,
            explanation=gen_result.explanation,
            guardrail_rejection_reason=guardrail_res.rejection_reason,
            filtered_tables=filtered_tables,
            constructed_prompt=full_constructed_prompt,
            few_shots_count=len(few_shots),
        )

    # --- STEP 5: Sandboxed Execution & Auto-Healing Refinement ---
    llm_pipeline = SQLGeneratorPipeline(db_url=db_url)
    refiner = SQLRefinedEngine(llm_client=llm_pipeline, db_url=db_url)

    refine_res = refiner.execute_and_refine(
        initial_sql=guardrail_res.sanitized_sql,
        schema_context=formatted_schema,
        question=user_question,
    )

    if not refine_res.is_successful or not refine_res.execution_result:
        return PipelineResult(
            status="EXECUTION_FAILED",
            question=user_question,
            generated_sql=gen_result.sql,
            explanation=gen_result.explanation,
            error_message=refine_res.last_error,
            filtered_tables=filtered_tables,
            constructed_prompt=full_constructed_prompt,
            few_shots_count=len(few_shots),
        )

    exec_data = refine_res.execution_result.data
    final_sql = refine_res.final_sql

    final_answer = llm_pipeline.generate_final_answer(question=user_question, data=exec_data)

    # --- STEP 6: Hallucination Detection, Sanity Check, Multi-Query Consensus ---
    backtranslator = BacktranslationVerifier()
    bt_res = backtranslator.verify_hallucination(
        original_question=user_question,
        generated_sql=final_sql,
        schema_context=formatted_schema,
    )

    sanity_checker = ResultSanityChecker()
    sanity_res = sanity_checker.check_sanity(exec_data)

    consensus_res = None
    try:
        consensus_validator = MultiQueryValidator()
        variants = consensus_validator.generate_variants(
            question=user_question, schema_context=formatted_schema
        )

        variant_2_guardrail_res = middleware.validate_and_sanitize(variants.query_variant_2)

        if not variant_2_guardrail_res.is_safe:
            data_variant_2 = []
            sql_variant_2 = variants.query_variant_2
        else:
            sandbox = SafeQuerySandbox(db_url=db_url)
            try:
                exec_variant_2 = sandbox.execute_query(variant_2_guardrail_res.sanitized_sql)
                data_variant_2 = exec_variant_2.data if exec_variant_2.success else []
                sql_variant_2 = variant_2_guardrail_res.sanitized_sql
            finally:
                sandbox.close()

        consensus_res = consensus_validator.evaluate_consensus(
            sql_1=final_sql,
            data_1=exec_data,
            sql_2=sql_variant_2,
            data_2=data_variant_2,
        )
    except Exception:
        consensus_res = None

    # --- STEP 7: Confidence Scoring ---
    scorer = ConfidenceScoringEngine()
    confidence_report = scorer.calculate_confidence(
        is_syntax_valid=True,
        backtranslation_res=bt_res,
        sanity_res=sanity_res,
        consensus_res=consensus_res,
    )

    return PipelineResult(
        status="SUCCESS",
        question=user_question,
        generated_sql=final_sql,
        explanation=gen_result.explanation,
        natural_language_answer=final_answer,
        data=exec_data,
        row_count=len(exec_data),
        confidence_report=confidence_report,
        filtered_tables=filtered_tables,
        constructed_prompt=full_constructed_prompt,
        few_shots_count=len(few_shots),
    )