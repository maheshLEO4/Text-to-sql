import os
import sqlparse
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from generation.prompt_constructor import PromptConstructor, FewShotExample

load_dotenv(override=True)


def get_model_name(model_name: str | None = None) -> str:
    """Resolve the Groq LLM model from the environment and allow direct override."""
    configured_name = (model_name or os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant").strip()
    if configured_name == "openai/gpt-oss-120b":
        return "llama-3.1-8b-instant"
    return configured_name


class SQLGenerationResponse(BaseModel):
    """
    Structured response schema enforced via LangChain + Groq Function Calling.
    """
    sql: str = Field(
        ..., 
        description="The executable PostgreSQL query without code markdown blocks or backticks."
    )
    explanation: str = Field(
        ..., 
        description="A concise explanation of what the generated SQL query does."
    )
    confidence_score: float = Field(
        ..., 
        description="Self-assessed confidence score between 0.0 and 1.0 based on available schema context."
    )
    tables_accessed: List[str] = Field(
        default_factory=list, 
        description="List of table names referenced in the query."
    )
    columns_accessed: List[str] = Field(
        default_factory=list, 
        description="List of column names referenced in the query."
    )


class SQLGenerator:
    """
    Handles SQL generation using LangChain (ChatGroq) and Function Calling
    to strictly enforce structured JSON outputs and syntax validation.
    """

    def __init__(self, model_name: str | None = None):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in environment variables.")

        resolved_model_name = get_model_name(model_name)

        # Initialize LangChain Groq Chat model
        self.llm = ChatGroq(
            model=resolved_model_name,
            temperature=0.0,  # Zero temperature for deterministic SQL generation
            groq_api_key=api_key,
        )

        # JSON mode avoids forcing a tool call on models that sometimes answer
        # directly instead of emitting the requested function invocation.
        self.structured_llm = self.llm.with_structured_output(
            SQLGenerationResponse,
            method="json_mode"
        )

    def validate_sql_syntax(self, sql_query: str) -> bool:
        """
        Validates basic SQL syntax and formatting using sqlparse.
        Returns True if syntactically parseable, False otherwise.
        """
        if not sql_query or not sql_query.strip():
            return False

        try:
            parsed = sqlparse.parse(sql_query)
            return len(parsed) > 0 and parsed[0].get_type() != "UNKNOWN"
        except Exception:
            return False

    def generate_sql(
        self,
        question: str,
        formatted_schema: str,
        glossary: Optional[str] = None,
        few_shots: Optional[List[FewShotExample]] = None
    ) -> SQLGenerationResponse:
        """
        Constructs system and user prompts and invokes the LangChain Groq model
        using function calling to receive structured Pydantic output.
        """
        # Assemble prompts using your Phase 1 PromptConstructor
        constructor = PromptConstructor(glossary=glossary, few_shots=few_shots)
        system_prompt = constructor.build_system_prompt(formatted_schema)
        user_prompt = constructor.build_user_prompt(question)

        # Build LangChain ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_prompt}"),
            ("user", "{user_prompt}")
        ])

        # Chain prompt assembly with the structured Groq LLM
        chain = prompt | self.structured_llm

        # Invoke chain
        raw_response = chain.invoke({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        })

        if not raw_response:
            raise ValueError("Failed to retrieve structured output from LangChain ChatGroq.")

        if isinstance(raw_response, dict) and raw_response.get("error"):
            raise ValueError(f"Groq model returned an error: {raw_response['error']}")

        # Some LangChain/Groq versions return a dict even when a Pydantic
        # schema is supplied. Normalize both forms at this boundary so the
        # rest of the pipeline can rely on SQLGenerationResponse attributes.
        response = (
            raw_response
            if isinstance(raw_response, SQLGenerationResponse)
            else SQLGenerationResponse.model_validate(raw_response)
        )

        # Clean trailing semicolons & whitespace
        response.sql = response.sql.strip().rstrip(";")

        # Validate syntax
        if not self.validate_sql_syntax(response.sql):
            raise ValueError(f"LangChain generated syntactically invalid SQL:\n{response.sql}")

        return response


# Local Execution Verification
if __name__ == "__main__":
    import sys
    # schema_extractor.py lives in the sibling 01_schema/ folder
    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    _SCHEMA_DIR = os.path.join(os.path.dirname(_THIS_DIR), "01_schema")
    if _SCHEMA_DIR not in sys.path:
        sys.path.insert(0, _SCHEMA_DIR)

    from schema_extractor import SchemaExtractor

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Please set DATABASE_URL in .env to run local verification.")
        exit(1)

    print("Extracting dynamic schema...")
    extractor = SchemaExtractor(db_url)
    schema = extractor.extract_full_schema()
    formatted_schema = extractor.format_schema_for_prompt(schema)

    # Initialize SQL Generator using the configured Groq model from .env
    generator = SQLGenerator()
    test_question = "How many  customers are there?"

    print(f"Generating SQL with LangChain + Groq for question: '{test_question}'...")
    try:
        result = generator.generate_sql(
            question=test_question,
            formatted_schema=formatted_schema
        )
        print("\n--- GENERATION SUCCESS ---")
        print(f"SQL:\n{result.sql}")
        print(f"Explanation: {result.explanation}")
        print(f"Confidence: {result.confidence_score}")
        print(f"Tables Accessed: {result.tables_accessed}")
        print(f"Columns Accessed: {result.columns_accessed}")
    except Exception as e:
        print(f"\nGeneration failed: {e}")