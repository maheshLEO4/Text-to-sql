import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel

from ingestion.schema_extractor import SchemaExtractor

# Load environment variables from .env file
load_dotenv()


class FewShotExample(BaseModel):
    question: str
    sql: str
    explanation: Optional[str] = ""
    category: Optional[str] = ""
    usage_count: int = 0


class PromptConstructor:
    """
    Assembles dynamic system and user prompts for Text-to-SQL generation.
    Completely schema-agnostic and reusable across any PostgreSQL database.
    """

    def __init__(
        self,
        glossary: Optional[str] = None,
        few_shots: Optional[List[FewShotExample]] = None,
        dialect: str = "PostgreSQL",
        feedback_dir: Optional[str] = None,
    ):
        self.dialect = dialect
        self.glossary = glossary or "No domain-specific glossary provided. Follow standard database conventions."
        self.few_shots = few_shots or self._load_feedback_examples(feedback_dir=feedback_dir)

    @staticmethod
    def _load_feedback_examples(feedback_dir: Optional[str] = None, top_k: int = 5) -> List[FewShotExample]:
        """Load saved few-shot examples from the feedback file, if present."""
        base_dir = Path(feedback_dir) if feedback_dir else Path("data") / "feedback"
        examples_file = base_dir / "few_shot_examples.json"

        if not examples_file.exists():
            return []

        try:
            with examples_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return []

        if not isinstance(payload, list):
            return []

        converted: List[FewShotExample] = []
        for item in payload[:top_k]:
            if not isinstance(item, dict):
                continue

            sql = item.get("generated_sql") or item.get("sql") or ""
            question = item.get("question") or ""
            if not question or not sql:
                continue

            converted.append(
                FewShotExample(
                    question=question,
                    sql=sql,
                    explanation=item.get("natural_language_answer") or item.get("explanation") or "",
                    category=item.get("category") or "",
                    usage_count=int(item.get("usage_count") or 0),
                )
            )

        return converted

    def build_system_prompt(self, schema_text: str) -> str:
        """Dynamically constructs the system prompt using extracted schema and provided context."""
        
        if self.few_shots:
            shot_blocks = []
            for ex in self.few_shots:
                block = f"Question: {ex.question}\nSQL:\n{ex.sql}"
                if ex.explanation:
                    block += f"\nExplanation: {ex.explanation}"
                shot_blocks.append(block)
            few_shot_str = "\n\n".join(shot_blocks)
        else:
            few_shot_str = "No few-shot examples provided. Rely strictly on the schema and standard SQL dialect rules."

        system_prompt = f"""You are an expert {self.dialect} Data Engineer. Your task is to translate natural language questions into valid, syntactically correct {self.dialect} queries.

### DATABASE DIALECT:
{self.dialect}

### RULES & CONSTRAINTS:
1. ONLY generate read-only SELECT queries. Never generate DROP, ALTER, INSERT, UPDATE, DELETE, or TRUNCATE statements.
2. Rely strictly on the schema provided below. Do not assume or invent tables or columns not present in the schema.
3. Pay close attention to Foreign Key mappings for table JOINs.
4. Always apply sample string values when filtering string columns to avoid casing or spelling mismatches.
5. Use proper {self.dialect} date, string, and aggregation functions.

### BUSINESS GLOSSARY & DEFINITIONS:
{self.glossary}

### DATABASE SCHEMA:
{schema_text}

### FEW-SHOT EXAMPLES:
{few_shot_str}
"""
        return system_prompt

    def build_user_prompt(self, question: str) -> str:
        """Constructs the final user prompt wrapping the question."""
        return f"User Question: {question}\n\nGenerate the corresponding SQL query."


# Local Verification Execution
if __name__ == "__main__":
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not found! Please check your .env file.")

    print("Extracting live schema dynamically from connected database...")
    extractor = SchemaExtractor(DATABASE_URL)
    schema = extractor.extract_full_schema()
    schema_text = extractor.format_schema_for_prompt(schema)

    constructor = PromptConstructor()
    system_p = constructor.build_system_prompt(schema_text)
    user_p = constructor.build_user_prompt("How many total records exist across orders?")

    print("\n--- FULL GENERATED SYSTEM PROMPT ---")
    print(system_p)
    print("\n--- GENERATED USER PROMPT ---")
    print(user_p)