import os
import sys
import json
from dotenv import load_dotenv


# Import Phase 1 components
from ingestion.schema_extractor import SchemaExtractor
from ingestion.schema_filter import SchemaFilter
from generation.prompt_constructor import PromptConstructor
from generation.ambiguity_handler import DynamicAmbiguityHandler

# Import Phase 2 components
from generation.sql_generator import SQLGenerator
from safety.guardrails import SQLGuardrailMiddleware
from safety.query_sandbox import SafeQuerySandbox
from safety.sql_refiner import SQLRefinedEngine
from generation.llm_client import SQLGeneratorPipeline

# Import Phase 3 components
from verification.hallucination_detector import BacktranslationVerifier
from verification.result_sanity_checker import ResultSanityChecker
from verification.multi_query_validator import MultiQueryValidator
from verification.confidence_scorer import ConfidenceScoringEngine

load_dotenv()


def run_full_text_to_sql_pipeline(user_question: str):
    print("=" * 80)
    print(f"  RUNNING COMPLETE PIPELINE FOR: '{user_question}'")
    print("=" * 80)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ ERROR: DATABASE_URL is not set in environment variables.")
        return

    # -------------------------------------------------------------------------
    # STEP 1: Live Schema Extraction & Filtering (Phase 1)
    # -------------------------------------------------------------------------
    print("\n--- STEP 1: Schema Extraction & RAG Filtering ---")
    extractor = SchemaExtractor(db_url)
    full_schema = extractor.extract_full_schema()

    schema_filter = SchemaFilter(full_schema)
    filtered_schema = schema_filter.filter_schema(user_question, top_k=5)
    formatted_schema = schema_filter.format_for_prompt(filtered_schema)

    print(f"✅ Filtered to {len(filtered_schema)} relevant tables: {list(filtered_schema.keys())}")

    # -------------------------------------------------------------------------
    # STEP 2: Ambiguity Analysis (Phase 1)
    # -------------------------------------------------------------------------
    print("\n--- STEP 2: Dynamic Ambiguity Check ---")
    ambiguity_handler = DynamicAmbiguityHandler()
    # NOTE: the real handler only exposes check_ambiguity_mock(question) until
    # Phase 2 LLM wiring is connected — there is no analyze_ambiguity() method.
    ambiguity_res = ambiguity_handler.check_ambiguity_mock(user_question)

    if ambiguity_res.is_ambiguous:
        print(f"⚠️ Ambiguity Flagged on term: '{ambiguity_res.ambiguous_term}'")
        print("Clarification Options:")
        for interp in ambiguity_res.interpretations:
            print(f"  [{interp.id}] {interp.label}: {interp.description}")
    else:
        print("✅ No ambiguity detected. Proceeding.")

    # -------------------------------------------------------------------------
    # STEP 3: Prompt Construction & SQL Generation (Phase 2)
    # -------------------------------------------------------------------------
    print("\n--- STEP 3: SQL Generation ---")
    prompt_builder = PromptConstructor(dialect="PostgreSQL")
    system_prompt = prompt_builder.build_system_prompt(formatted_schema)
    user_prompt = prompt_builder.build_user_prompt(user_question)

    sql_gen = SQLGenerator()
    gen_result = sql_gen.generate_sql(
        question=user_question,
        formatted_schema=formatted_schema
    )
    print(f"📌 Generated SQL:\n{gen_result.sql}")
    print(f"💡 Explanation: {gen_result.explanation}")
    print(f"🎯 Confidence Score: {gen_result.confidence_score}")

    # -------------------------------------------------------------------------
    # STEP 4: Guardrail Validation (Phase 2)
    # -------------------------------------------------------------------------
    print("\n--- STEP 4: Guardrail Middleware Validation ---")
    middleware = SQLGuardrailMiddleware(db_url=db_url)
    guardrail_res = middleware.validate_and_sanitize(gen_result.sql)

    if not guardrail_res.is_safe:
        print(f"❌ Guardrail Failure: {guardrail_res.rejection_reason}")
        return

    print(f"✅ Guardrails Passed. Sanitized Query:\n{guardrail_res.sanitized_sql}")

    # -------------------------------------------------------------------------
    # STEP 5: Sandboxed Execution & Auto-Healing Refinement (Phase 2)
    # -------------------------------------------------------------------------
    print("\n--- STEP 5: Sandboxed Execution & Refinement ---")
    llm_pipeline = SQLGeneratorPipeline(db_url=db_url)
    refiner = SQLRefinedEngine(llm_client=llm_pipeline, db_url=db_url)

    refine_res = refiner.execute_and_refine(
        initial_sql=guardrail_res.sanitized_sql,
        schema_context=formatted_schema,
        question=user_question
    )

    if not refine_res.is_successful or not refine_res.execution_result:
        print(f"❌ Sandbox Execution Failed: {refine_res.last_error}")
        return

    exec_data = refine_res.execution_result.data
    final_sql = refine_res.final_sql
    print(f"✅ Executed Successfully ({refine_res.execution_result.row_count} rows returned)")

    # Generate a plain-English answer from the retrieved data
    final_answer = llm_pipeline.generate_final_answer(
        question=user_question,
        data=exec_data
    )
    print(f"\n💬 NATURAL LANGUAGE ANSWER:\n{final_answer}")

    # -------------------------------------------------------------------------
    # STEP 6: Phase 3 Validation & Hallucination Verification
    # -------------------------------------------------------------------------
    print("\n--- STEP 6: Phase 3 Hallucination & Sanity Verification ---")

    # 6a. Backtranslation Verification
    backtranslator = BacktranslationVerifier()
    bt_res = backtranslator.verify_hallucination(
        original_question=user_question,
        generated_sql=final_sql,
        schema_context=formatted_schema
    )

    # 6b. Result Sanity Checking
    sanity_checker = ResultSanityChecker()
    sanity_res = sanity_checker.check_sanity(exec_data)

    # 6c. Multi-Query Consensus Verification
    consensus_res = None
    try:
        consensus_validator = MultiQueryValidator()
        variants = consensus_validator.generate_variants(
            question=user_question,
            schema_context=formatted_schema
        )

        # Every independently generated SQL variant must pass the SAME
        # guardrail checks as the primary query before it ever touches the
        # sandbox. Relying only on the DB's read-only transaction as the
        # backstop means a variant can still be blocked *after* an unsafe
        # statement was constructed — guardrails should catch it first.
        variant_2_guardrail_res = middleware.validate_and_sanitize(variants.query_variant_2)

        if not variant_2_guardrail_res.is_safe:
            print(
                f"⚠️ Variant 2 SQL blocked by guardrails "
                f"(reason: {variant_2_guardrail_res.rejection_reason}). "
                f"Treating as non-consensus / empty result."
            )
            data_variant_2 = []
            sql_variant_2 = variants.query_variant_2
        else:
            sandbox = SafeQuerySandbox(db_url=db_url)
            exec_variant_2 = sandbox.execute_query(variant_2_guardrail_res.sanitized_sql)
            data_variant_2 = exec_variant_2.data if exec_variant_2.success else []
            sql_variant_2 = variant_2_guardrail_res.sanitized_sql

        consensus_res = consensus_validator.evaluate_consensus(
            sql_1=final_sql,
            data_1=exec_data,
            sql_2=sql_variant_2,
            data_2=data_variant_2
        )
    except Exception as e:
        print(f"⚠️ Consensus validation skipped: {e}")
        consensus_res = None

    # -------------------------------------------------------------------------
    # STEP 7: Confidence Scoring Engine Report
    # -------------------------------------------------------------------------
    print("\n--- STEP 7: Confidence Report Generation ---")
    scorer = ConfidenceScoringEngine()
    confidence_report = scorer.calculate_confidence(
        is_syntax_valid=True,
        backtranslation_res=bt_res,
        sanity_res=sanity_res,
        consensus_res=consensus_res
    )

    # -------------------------------------------------------------------------
    # FINAL OUTPUT PRESENTATION
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("🎉 FULL PIPELINE SUCCESSFUL EXECUTION & VALIDATION!")
    print("=" * 80)

    print(f"\n📊 FINAL CONFIDENCE REPORT:")
    print(f"   • Composite Score : {confidence_report.composite_confidence_score} / 1.0")
    print(f"   • Confidence Tier : {confidence_report.confidence_tier}")
    print(f"   • All Layers Passed: {confidence_report.passed_all_layers}")

    print("\n🔍 SIGNAL BREAKDOWN:")
    for signal, val in confidence_report.signal_breakdown.items():
        print(f"   • {signal}: {val}")

    if confidence_report.warnings:
        print("\n⚠️ WARNINGS:")
        for w in confidence_report.warnings:
            print(f"   • {w}")

    if confidence_report.critical_issues:
        print("\n🚨 CRITICAL ISSUES:")
        for ci in confidence_report.critical_issues:
            print(f"   • {ci}")

    print(f"\n💬 NATURAL LANGUAGE ANSWER:\n{final_answer}")
    print(f"\n💻 FINAL EXECUTED SQL:\n{final_sql}")
    print(f"\n📋 SAMPLE OUTPUT DATA (First 3 Rows):")
    for row in exec_data[:3]:
        print(f"  {row}")


if __name__ == "__main__":
    while True:
        test_q = input("\nEnter a natural language question (or 'exit' to quit): ")
        if test_q.lower() == "exit":
            print("Exiting pipeline test harness.")
            break
        if len(sys.argv) > 1:
            test_q = sys.argv[1]

        run_full_text_to_sql_pipeline(test_q)