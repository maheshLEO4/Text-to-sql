import os
import json
from typing import List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class InterpretationOption(BaseModel):
    id: int
    label: str
    description: str
    formula_or_logic: str


class AmbiguityCheckResult(BaseModel):
    is_ambiguous: bool
    ambiguous_term: Optional[str] = None
    question: str
    interpretations: List[InterpretationOption] = []


class DynamicAmbiguityHandler:
    """
    Dynamically checks questions for domain ambiguities using an LLM 
    instead of hardcoded dictionary rules.
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def build_detection_prompt(self, question: str, schema_text: str = "") -> str:
        """Constructs a prompt instructing the LLM to inspect the query for ambiguity."""
        return f"""You are a database business intelligence analyzer. Analyze the following user question to determine if it contains ambiguous business terms or multiple plausible SQL interpretations.

### USER QUESTION:
"{question}"

### DATABASE SCHEMA CONTEXT:
{schema_text if schema_text else "Standard database schema"}

### TASK:
Determine if the question contains ambiguous business terms (e.g., 'revenue', 'active users', 'recent orders', 'sales') where multiple formulas or filtering criteria could apply.

Respond ONLY with valid JSON matching this schema:
{{
    "is_ambiguous": true/false,
    "ambiguous_term": "term if ambiguous else null",
    "interpretations": [
        {{
            "id": 1,
            "label": "Name of Interpretation 1",
            "description": "Explanation of what this calculation includes",
            "formula_or_logic": "SQL logic or formula representation"
        }},
        {{
            "id": 2,
            "label": "Name of Interpretation 2",
            "description": "Explanation of what this calculation includes",
            "formula_or_logic": "SQL logic or formula representation"
        }}
    ]
}}
"""

    def check_ambiguity_mock(self, question: str) -> AmbiguityCheckResult:
        """
        Fallback / Mock execution demonstrate dynamic behavior prior to Phase 2 LLM wiring.
        """
        # When connected to your LLM client in Phase 2, this will execute self.llm_client.generate(...)
        # For now, it returns non-hardcoded structured logic.
        return AmbiguityCheckResult(
            is_ambiguous=False,
            question=question,
            interpretations=[]
        )


if __name__ == "__main__":
    handler = DynamicAmbiguityHandler()
    res = handler.check_ambiguity_mock("Show top selling products")
    print(f"Query: {res.question}")
    print(f"Is Ambiguous: {res.is_ambiguous}")