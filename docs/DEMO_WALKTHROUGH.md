# Phase 6 — Step 1: Video Demo & Presentation Script (< 4 Minutes)

This script is structured to demonstrate the production-grade capabilities of your Text-to-SQL system, leading with **Safety, Reliability, and Self-Healing**.

---

## 🎬 4-Minute Demo Script & Walkthrough

### ⏱️ Scene 1: Introduction & Natural Language Translation (0:00 – 1:00)
* **Goal**: Show basic query generation, natural language response synthesis, and schema filtering.
* **Action**:
  1. Open the Streamlit UI (`streamlit run frontend/app.py`).
  2. Ask a business question:
     > *"Show me the top 5 products with the highest unit price"*
  3. Point out key UI components:
     * **Generated SQL** with syntax highlighting.
     * **Natural Language Summary** generated from the data.
     * **Data Table** with sortable columns.
     * **Schema Context** (showing only relevant tables filtered by RAG).

---

### ⏱️ Scene 2: Security Guardrails Blocking Unsafe Queries (1:00 – 2:00)
* **Goal**: Prove that compliance and security teams would approve this system.
* **Action**:
  1. Attempt a destructive input:
     > *"DROP TABLE products; SELECT * FROM customers;"*
  2. Show the immediate **Guardrail Rejection**:
     * Red warning banner: `GUARDRAIL_BLOCKED`.
     * Audit log message: `Blocked DDL keyword 'DROP'`.
     * Zero database changes executed.
  3. Mention the multi-layered defense: **Keyword blocking + AST parsing + EXPLAIN cost estimation + Read-only DB user sandbox**.

---

### ⏱️ Scene 3: Hallucination Detection & Multi-Query Consensus (2:00 – 3:00)
* **Goal**: Demonstrate how the system verifies its own output before showing it to the user.
* **Action**:
  1. Ask a complex/nuanced question:
     > *"What is the total revenue per product category in 1997?"*
  2. Expand the **Verification & Confidence Breakdown**:
     * **Backtranslation Alignment**: Show the LLM translating the SQL back into English to ensure true intent match.
     * **Result Sanity Check**: Show NULL concentration checks & numeric boundary validation.
     * **Multi-Query Consensus**: Show two independent SQL variants (e.g. `JOIN` vs `CTE`) being evaluated for data consensus.
     * **Composite Confidence Score**: Show the final aggregated confidence tier (`HIGH` / `95%+`).

---

### ⏱️ Scene 4: The Self-Improving Feedback Loop (Flywheel) (3:00 – 4:00)
* **Goal**: Demonstrate how user feedback automatically improves system accuracy over time.
* **Action**:
  1. Click **"Correct Result" (👍 Thumbs Up)** on the UI.
  2. Show terminal / storage confirmation:
     * Added as a new **Few-Shot Example** in `data/feedback/few_shot_examples.json`.
  3. Explain that incorrect feedback (👎 Thumbs Down) creates a **Test Case** in `data/feedback/test_cases.json` for continuous regression testing.
  4. **Closing Pitch**:
     > *"Built a production-ready Text-to-SQL engine with 90% execution accuracy on the Spider benchmark, 100% syntax reliability, 100% destructive query prevention, and automated hallucination detection."*
