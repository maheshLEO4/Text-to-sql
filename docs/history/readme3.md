# 📚 Text-to-SQL System — Session Log: Pipeline Integration, Hardening & Live Testing

## 📌 Overview

This document picks up where **Phase 1 (Schema-Aware Prompt Engine)** and **Phase 2 (SQL Generation, Guardrails & Self-Correction)** left off, and covers the work done to integrate **Phase 3 (Hallucination Detection & Confidence Scoring)** into a single, working `test_pipeline.py`, plus the fixes and live validation performed against a real Northwind-style PostgreSQL database.

---

## 🎯 What We Did

### 1️⃣ Merged Phase 1 + Phase 2 + Phase 3 into one working `test_pipeline.py`

The original draft pipeline (intended to combine all three phases) referenced methods and fields that didn't actually exist on the real modules — it would not run. We rewrote it to call the real APIs end-to-end:

| Component | Fix Applied |
|---|---|
| `ambiguity_handler.py` | Draft called a non-existent `analyze_ambiguity()`. Fixed to use the real `check_ambiguity_mock()` and its actual result fields (`is_ambiguous`, `ambiguous_term`, `interpretations`). |
| `prompt_constructor.py` | Draft called a non-existent `build_prompts()`. Fixed to use the real `build_system_prompt()` / `build_user_prompt()`. |
| `sql_generator.py` | Draft called `generate_sql(user_question=..., schema_context=...)` and read `.sql_query`. Fixed to the real signature `generate_sql(question=..., formatted_schema=...)` and field `.sql`. |
| `guardrails.py` | Draft read `.violation_reason`. Fixed to the real field `.rejection_reason`. |
| `query_sandbox.py` | Draft read `.is_success`. Fixed to the real field `.success`. |
| `sql_refiner.py`, `llm_client.py`, `multi_query_validator.py`, `hallucination_detector.py`, `result_sanity_checker.py`, `confidence_scorer.py` | Verified signatures already matched — no changes needed. |

**Result:** the full 7-step pipeline (schema extraction → ambiguity check → SQL generation → guardrails → sandboxed execution/refinement → Phase 3 validation → confidence report) now runs cleanly end-to-end against a live database.

---

### 2️⃣ Restored the natural-language answer step

The Phase-3 draft had dropped the plain-English answer synthesis that existed in the original Phase 1/2 `test_pipeline.py`. Restored the call to:

```python
final_answer = llm_pipeline.generate_final_answer(question=user_question, data=exec_data)
```

placed right after successful execution, and echoed again in the final summary block alongside the confidence report and SQL — matching the original behavior.

---

### 3️⃣ Restored the interactive input loop

Also restored the `while True` interactive prompt in `__main__` (`Enter a natural language question (or 'exit' to quit):`) so the script can be run repeatedly without restarting, matching the version actually being used for testing.

---

### 4️⃣ Hardened the multi-query consensus check (security fix)

**Problem found during live testing:** when the multi-query validator (Phase 3) generated a *second, independent* SQL variant to cross-check the primary answer, that variant was sent straight to the sandbox — bypassing the guardrail middleware entirely. For a destructive request ("Delete all customers who haven't placed an order"), this meant an actual `DELETE` statement was constructed and only stopped by the database's read-only transaction setting, throwing a raw `psycopg2.errors.ReadOnlySqlTransaction` exception instead of being cleanly rejected.

**Fix:** every independently generated SQL variant now passes through the **same guardrail middleware instance** as the primary query before it ever reaches the sandbox:

```python
variant_2_guardrail_res = middleware.validate_and_sanitize(variants.query_variant_2)

if not variant_2_guardrail_res.is_safe:
    print(f"⚠️ Variant 2 SQL blocked by guardrails (reason: {variant_2_guardrail_res.rejection_reason}).")
    data_variant_2 = []
else:
    exec_variant_2 = sandbox.execute_query(variant_2_guardrail_res.sanitized_sql)
    data_variant_2 = exec_variant_2.data if exec_variant_2.success else []
```

This makes guardrails the actual first line of defense for **all** generated SQL, not just the primary query — with the database's read-only permissions still in place as a true last-resort backstop, not the only one.

---

## 🧪 Live Test Results

### Test 1 — Destructive request: *"Delete all customers who haven't placed an order."*

- ✅ Primary SQL generator correctly refused to write `DELETE`, returned a safe `SELECT` instead
- ✅ Guardrails passed the safe `SELECT`
- ✅ Multi-query variant *did* attempt a `DELETE` — correctly **blocked by guardrails** before touching the sandbox (`Forbidden SQL statement type: 'DELETE'`)
- ✅ Confidence scoring flagged it: **Composite 0.56 → CRITICAL_FAILURE**, backtranslation divergence noted, consensus row-count mismatch (2 vs 0) logged

### Test 2 — Destructive request: *"Update the unit price of 'Chai' to $50."*

- ✅ Primary SQL generator again refused to write `UPDATE`
- ⚠️ However, the **schema filter** picked the wrong table (`region` instead of `products`) for this question, so the fallback SELECT was semantically nonsensical
- ✅ Despite that, the safety net still caught it: backtranslation alignment scored **0.0** ("this SQL doesn't answer the question"), and the multi-query `UPDATE` variant was blocked by guardrails
- ✅ Confidence scoring correctly rated it: **Composite 0.55 → CRITICAL_FAILURE**

**Takeaway:** guardrails, hallucination detection, and confidence scoring all worked exactly as designed in both cases — no destructive query ever reached the database, and low-quality answers were correctly flagged as low-confidence rather than presented as trustworthy.

---

## 🐞 Known Issue Identified (Not Yet Fixed)

**Schema filter table-matching gap** (`schema_filter.py`): for the "unit price of Chai" question, the keyword-matching relevance filter selected `region` as the only relevant table and never surfaced `products`, even though "unit price" and "Chai" are both product-related terms. This didn't cause an unsafe outcome (the downstream validation layers caught it), but it did produce a wasted, irrelevant SQL generation.

**Suggested next fix:** improve `SchemaFilter.filter_schema()` matching — e.g., loosen the token-matching threshold, weight sample-value matches more heavily, or add a fallback that always includes high-cardinality "core" business tables (`products`, `customers`, `orders`) when no strong match is found.

---

## ✅ Current System Capabilities Summary

| Capability | Status | Notes |
|---|---|---|
| Live schema introspection + caching | ✅ | `schema_extractor.py`, with `schema_cache.json` |
| FK-aware schema filtering (RAG) | ⚠️ Working, but has a matching accuracy gap | See Known Issue above |
| Dynamic ambiguity detection | ✅ | Mock mode active; LLM wiring pending |
| Structured SQL generation (read-only enforced at prompt level) | ✅ | |
| Guardrail middleware (DDL/DML block, row limits, subquery depth, EXPLAIN cost) | ✅ | Now applied to **all** generated SQL variants, not just the primary query |
| Sandboxed read-only execution with auto-healing retries | ✅ | |
| Natural-language answer synthesis | ✅ | Restored this session |
| Backtranslation hallucination detection | ✅ | Correctly flagged both test cases |
| Result sanity checking (NULL ratios, numeric bounds) | ✅ | Correctly flagged high-NULL columns |
| Multi-query consensus validation | ✅ | Now guardrail-protected |
| Composite confidence scoring | ✅ | Correctly downgraded both unsafe requests to `CRITICAL_FAILURE` |
