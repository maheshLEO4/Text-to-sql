📚 Production-Ready Text-to-SQL System: Comprehensive Documentation (Phase 1 & Phase 2)

📌 Executive Summary

This document provides complete architectural and functional documentation for the Production-Ready Text-to-SQL System built across Phase 1 (Schema-Aware Prompt Engine) and Phase 2 (LLM SQL Generation, Guardrail Security & Self-Correction Pipeline).



The system translates natural language business questions into precise PostgreSQL queries, validates them against strict read-only and performance guardrails, and executes them in a sandboxed database environment with automatic self-correction upon execution errors.



🏗️ System Architecture Overview

The end-to-end flow consists of 6 distinct pipeline steps:



[ Natural Language Question ]
             │
             ▼
1️⃣ Schema Extraction & FK-Aware Filtering (RAG)
             │
             ▼
2️⃣ Dynamic Business Ambiguity Detection
             │
             ▼
3️⃣ Token-Optimized Prompt Assembly
             │
             ▼
4️⃣ Structured LLM SQL Generation
             │
             ▼
5️⃣ Pre-Execution Safety Guardrails & Sanity Check
             │
             ▼
6️⃣ Sandboxed Query Execution & Self-Correction Refinement Loop
             │
             ▼
[ Executed Output Data / Data Table ]


🛠️ Detailed Component Breakdown

📍 Phase 1: Schema-Aware Prompt Engine

1️⃣ Dynamic Schema Extractor (schema_extractor.py)

Purpose: Introspects connected live databases (PostgreSQL/Supabase) via SQLAlchemy.



Key Deliverables:



Extracts table names, column names, and data types.



Identifies Primary Keys (PK) and Foreign Keys (FK).



Fetches distinct sample text values per column to prevent string case and formatting mismatches.



Formats schema into structured context strings for LLMs.



2️⃣ FK-Aware Schema Filter (schema_filter.py)

Purpose: Implements dynamic context-window optimization (RAG).



Key Deliverables:



Tokenizes queries and scores tables based on relevant column/table matches.



Filters out unrelated database clutter while preserving Foreign Key relationships so multi-table JOIN queries do not fail.



3️⃣ Dynamic Ambiguity Handler (ambiguity_handler.py)

Purpose: Prevents standard LLM assumptions on vague business terms.



Key Deliverables:



Analyzes questions for ambiguous terms (e.g., "top-selling", "revenue", "active customers").



Formats clarification options with formulas/SQL logic before execution.



4️⃣ Prompt Builder (prompt_constructor.py)

Purpose: Assembles production-grade system and user prompts.



Key Deliverables:



Embeds PostgreSQL dialect rules and security constraints.



Ingests filtered schema, business glossary definitions, and few-shot query examples.



📍 Phase 2: LLM SQL Generation, Security & Self-Correction

5️⃣ Structured SQL Generator (sql_generator.py)

Purpose: Generates strict, valid PostgreSQL queries using LangChain and ChatGroq.



Key Deliverables:



Enforces structured Pydantic outputs (sql, explanation, confidence_score, tables_accessed, columns_accessed).



Guarantees valid SQL without markdown artifacts or backticks.



6️⃣ Read-Only & Performance Guardrails (guardrails.py)

Purpose: Prevents destructive database operations and unbounded heavy resource scans.



Key Deliverables:



Intercepts and validates generated SQL statements before execution.



Blocks forbidden DDL/DML statements (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE).



Automatically appends safety limits (LIMIT 1000).



Rejects deeply nested subqueries (> 3 levels deep).



Runs EXPLAIN cost analysis checks against PostgreSQL.



7️⃣ Sandboxed Execution Engine (query_sandbox.py)

Purpose: Safely runs approved SQL queries.



Key Deliverables:



Executes queries inside read-only transactional blocks (READ ONLY).



Enforces hard execution timeouts (default: 5 seconds).



Captures execution latency, returned row count, and dataset payloads.



8️⃣ Self-Correction & Refinement Engine (sql_refiner.py)

Purpose: Auto-heals broken queries without manual user intervention.



Key Deliverables:



Catches runtime database errors (e.g., missing columns, invalid JOINs, group-by issues).



Feeds exact database error messages back to the LLM for up to N retries (max_retries=3).



Re-evaluates healed queries through safety guardrails before executing.



🗂️ Project Directory Structure

Text-to-SQL/
│
├── .env                     # Database URLs & API keys
├── ambiguity_handler.py     # Dynamic ambiguity check
├── guardrails.py            # Pre-execution safety middleware
├── llm_client.py            # LLM client wrapper for raw prompts & refinement
├── prompt_constructor.py    # Schema-aware prompt builder
├── query_sandbox.py         # Sandboxed DB query executor
├── schema_extractor.py      # SQLAlchemy DB schema introspection
├── schema_filter.py         # FK-aware schema RAG filter
├── sql_generator.py         # LangChain + Groq structured SQL generation
├── sql_refiner.py           # Auto-healing self-correction loop
└── test_pipeline.py         # End-to-end integration test runner


🧪 Verification & Pipeline Execution

To run the complete Phase 1 & Phase 2 verification pipeline:

Bash

python test_pipeline.py


Verified Sample Output Log

Plaintext

================================================================================
  TESTING PIPELINE FOR QUESTION: 'Which products are the most expensive?'
================================================================================

--- STEP 1: Schema Extraction & RAG Filtering ---
✅ Filtered to 5 relevant tables: suppliers, products, region, customers, categories

--- STEP 2: Ambiguity Detection ---
✅ No critical ambiguity detected. Proceeding to prompt construction.

--- STEP 3: Prompt Construction ---
✅ System and User prompts constructed successfully.

--- STEP 4: LLM SQL Generation ---
📌 Generated SQL:
SELECT product_name, unit_price FROM products ORDER BY unit_price DESC
💡 Explanation: Selects product name and price, ordered descending to show most expensive items first.
🎯 Confidence Score: 1.0

--- STEP 5: Guardrail Safety Validation ---
✅ Guardrails Passed. Sanitized Query:
SELECT product_name, unit_price FROM products ORDER BY unit_price DESC LIMIT 1000

--- STEP 6: Sandboxed Query Execution & Self-Correction ---
🎉 PIPELINE SUCCESS!
📊 Rows Returned: 77
⏱️ Execution Time: 42.15 ms
Sample Output Data (First 3 rows):
  {'product_name': 'Côte de Blaye', 'unit_price': 263.5}
  {'product_name': 'Thüringer Rostbratwurst', 'unit_price': 123.79}
  {'product_name': 'Mishi Kobe Niku', 'unit_price': 97.0}


✅ Current System Capabilities Summary

Capability

Status

Description

Dynamic Schema Introspection

✅ Done

Fetches live schema metadata, PKs, FKs, and data sample types.

FK-Preserving RAG Filtering

✅ Done

Filters prompt context size while retaining join paths.

Dynamic Business Ambiguity Check

✅ Done

Flags vague business terminology for clarification.

Structured SQL Generation

✅ Done

Generates executable PostgreSQL queries using ChatGroq.

DDL/DML Guardrails

✅ Done

Blocks write/delete queries (DROP, DELETE, UPDATE, etc.).

EXPLAIN Cost Estimation

✅ Done

Enforces execution limits & resource consumption bounds.

Safe Query Sandbox

✅ Done

Executes in isolated READ ONLY database sessions with timeouts.

Auto-Healing Self-Correction

✅ Done

Feeds syntax & execution errors back to LLM for retry corrections.   give it in mark down file 