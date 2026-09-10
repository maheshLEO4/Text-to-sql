# 🚀 Phase 1 Documentation Summary: Schema-Aware Prompt Engine

In Phase 1, we established the core foundation of our production-grade **Text-to-SQL system**.

The main objective of this phase was to extract live context from the database and construct focused, token-optimized prompts that enable an LLM to generate accurate SQL without exceeding token limits or hallucinating non-existent tables.

---

## 📌 Architectural Workflow Overview

### 1. User Query Input

A plain-English question enters the system.

### 2. Dynamic Introspection

The database schema is fetched live, including:

* Tables
* Columns
* Data types
* Primary keys
* Foreign keys
* Sample categorical/text values

### 3. Foreign-Key-Aware Schema Filtering (RAG)

The user query is compared against:

* Table names
* Column names
* Categorical sample values

The system retains only relevant tables while preserving linked foreign-key tables to ensure valid SQL `JOIN` statements.

### 4. Dynamic Ambiguity Evaluation

The query is analyzed against the dynamic schema to detect ambiguous business definitions.

Examples include:

* Gross Revenue vs. Net Revenue
* Order Date vs. Shipped Date
* Customer Count vs. Order Count
* Revenue vs. Profit

When ambiguity is detected, the system produces structured options for clarification before SQL execution.

### 5. Prompt Assembly

System and user prompts are assembled using:

* Database rules
* Strict `SELECT`-only constraints
* Selected schema snippets
* Sample values
* Business glossary terms
* Few-shot examples

---

# 📂 Project Modules & Summary of Implementation

## 1️⃣ Database Introspection — `schema_extractor.py`

### Purpose

Connects directly to the PostgreSQL database through SQLAlchemy and dynamically inspects database metadata.

### What Was Built

* Automatically fetches all table structures.
* Extracts raw PostgreSQL column data types.
* Extracts Primary Key relationships.
* Extracts Foreign Key relationships.
* Retrieves non-null sample string values for text and categorical columns.
* Converts database metadata into a clean, text-formatted schema representation.

### Why Sample Values Matter

Sample values help the LLM generate exact string filters without guessing capitalization or spelling.

For example, instead of assuming a value is `Federal Shipping`, the system can inspect actual database values and use the correct representation.

This is particularly useful for:

* Company names
* Status codes
* Categories
* Country names
* Customer identifiers
* Other categorical fields

---

## 2️⃣ Schema Filtering / Context-Aware RAG — `schema_filter.py`

### Purpose

Prevents massive amounts of irrelevant database context from being sent to the LLM.

This helps:

* Reduce prompt token usage
* Reduce API costs
* Improve SQL generation accuracy
* Reduce hallucination
* Focus the LLM on relevant database structures

### What Was Built

#### Token-Matching System

Tables are scored and ranked based on keyword matches across:

* Table names
* Column names
* Sample values

The most relevant tables are selected for the final schema context.

#### Foreign-Key Dependency Preservation

When a relevant table is identified, the system automatically expands the selected table list to include related Foreign Key tables.

For example:

**Orders → Customers**

and:

**Orders → Shippers**

This ensures the LLM has access to the required tables and relationships for generating valid `JOIN` statements.

#### Fallback Logic

If no direct keyword matches are found, fallback logic preserves a standard full-schema output rather than returning an empty context.

This prevents the SQL generation pipeline from receiving insufficient schema information.

---

## 3️⃣ Dynamic Prompt Engineering — `prompt_constructor.py`

### Purpose

Assembles structured system and user prompts that are ready for LLM consumption.

### What Was Built

#### Environment Variable Integration

The project uses `.env` configuration through `python-dotenv`.

This allows sensitive database configuration to be stored outside the source code.

For example:

* Database connection information
* Credentials
* Environment-specific configuration

This prevents credentials from being hardcoded directly into Python files.

#### Rule Enforcement

The prompt contains strict PostgreSQL guardrails.

The generated SQL must be **read-only**.

Allowed:

* `SELECT`

Disallowed:

* `INSERT`
* `UPDATE`
* `DELETE`
* `DROP`
* `ALTER`
* `TRUNCATE`
* Other destructive operations

#### Context Ingestion

The prompt constructor dynamically integrates:

* Filtered schema
* Table relationships
* Sample values
* Business glossary
* Few-shot examples
* PostgreSQL-specific instructions

The resulting prompt provides the LLM with focused database context.

---

## 4️⃣ Dynamic Ambiguity Handler — `ambiguity_handler.py`

### Purpose

Identifies business terms or queries that have multiple plausible SQL interpretations instead of allowing the system to make blind assumptions.

### What Was Built

#### Dynamic LLM-Ready Prompt

A structured prompt template was designed to analyze the user's question against the available database schema.

The ambiguity handler considers:

* User terminology
* Available columns
* Available tables
* Business definitions
* Possible SQL interpretations

#### Structured Response Schema

Pydantic models were defined to capture ambiguity information in a structured format.

The response can contain:

* Flagged business terms
* Description of the ambiguity
* Candidate interpretations
* Mathematical formulas
* Possible SQL logic
* Clarification options

This allows the application to ask the user for clarification before generating or executing SQL.

---

# 🏁 Phase 1 Milestone Checklist

| Step  | Component                  | Status     | Key Deliverable                                                             |
| ----- | -------------------------- | ---------- | --------------------------------------------------------------------------- |
| **1** | **Live Schema Extractor**  | ✅ Complete | Introspects DB, extracts columns, PK/FK constraints, and string samples     |
| **2** | **Dynamic Prompt Builder** | ✅ Complete | Assembles PostgreSQL prompts with security rules and `.env` support         |
| **3** | **Schema Filter / RAG**    | ✅ Complete | Selects relevant tables and preserves Foreign Key dependencies              |
| **4** | **Ambiguity Detection**    | ✅ Complete | Generates structured prompts and output schemas for clarification workflows |

---

# 🔄 Complete Phase 1 Architecture

**User Question**

↓

**Live Database Schema Extraction**

↓

**Schema Filtering / RAG**

↓

**Foreign-Key Dependency Preservation**

↓

**Dynamic Ambiguity Detection**

↓

**Business Glossary + Few-Shot Context**

↓

**Dynamic Prompt Construction**

↓

**Schema-Aware Prompt**

---

# 📊 Phase 1 Capabilities

At the completion of Phase 1, the system can:

* 🔍 Dynamically understand the PostgreSQL database schema.
* 🧩 Identify tables and columns relevant to a natural-language question.
* 🔗 Preserve foreign-key dependencies required for SQL joins.
* 📝 Extract real database sample values.
* 🎯 Build token-optimized schema context.
* 🛡️ Enforce read-only SQL generation rules.
* 📚 Incorporate business glossary definitions.
* 🎓 Incorporate few-shot SQL examples.
* ❓ Detect potentially ambiguous business terminology.
* 📋 Produce structured ambiguity information for clarification.
* 🔐 Load database configuration securely through environment variables.

---

# 🏆 Phase 1 Completion Status

## Phase 1 — Schema-Aware Prompt Engine

**Status: 100% Complete ✅**

The system now has a complete schema-intelligence and prompt-engineering foundation.

The architecture can dynamically:

**Understand the Database**

↓

**Retrieve Relevant Schema**

↓

**Preserve Required Relationships**

↓

**Detect Ambiguity**

↓

**Build Focused Context**

↓

**Construct a Schema-Aware Prompt**

The foundation is now ready for the next stage of the Text-to-SQL system.
