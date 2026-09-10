import os
import re
from typing import Dict, Any, Tuple, List
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from sqlalchemy import create_engine, text

load_dotenv(override=True)


def get_model_name(model_name: str | None = None) -> str:
    """Resolve the LLM model from env, falling back to a safe Groq default."""
    return (model_name or os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant").strip()


class SQLGeneratorPipeline:
    """
    Executes Phase 2 SQL generation using LangChain and Groq, enforcing read-only guardrails,
    a retry/refinement loop for SQL execution errors, and final answer synthesis.
    """

    def __init__(self, db_url: str = None, model_name: str | None = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if not self.db_url:
            raise ValueError("DATABASE_URL is not set in environment variables.")

        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model_name = get_model_name(model_name)

        if not self.api_key:
            raise ValueError("GROQ_API_KEY environment variable is missing.")

        self.llm = ChatGroq(
            model=self.model_name,
            temperature=0,
            groq_api_key=self.api_key,
        )

    def is_safe_sql(self, sql_query: str) -> Tuple[bool, str]:
        """
        Guardrail check to ensure query is read-only (SELECT).
        Rejects DROP, DELETE, INSERT, UPDATE, ALTER, TRUNCATE, etc.
        """
        cleaned_sql = re.sub(r"--.*?\n", "", sql_query)
        cleaned_sql = re.sub(r"/\*.*?\*/", "", cleaned_sql, flags=re.DOTALL)
        statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]

        forbidden_keywords = {
            "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", 
            "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE"
        }

        for stmt in statements:
            tokens = [t.upper() for t in re.findall(r"\b\w+\b", stmt)]
            if not tokens:
                continue
            if tokens[0] != "SELECT" and tokens[0] != "WITH":
                return False, f"Guardrail Violation: Query must start with SELECT or WITH. Found '{tokens[0]}'."
            if any(kw in tokens for kw in forbidden_keywords):
                return False, f"Guardrail Violation: Query contains destructive operations."

        return True, "Safe"

    def generate(self, prompt: str) -> str:
        """Generate a raw text response from the underlying LLM for refinement loops."""
        return self.llm.invoke(prompt).content

    def execute_sql(self, sql_query: str) -> Dict[str, Any]:
        """Executes SQL safely against the database connection."""
        is_safe, msg = self.is_safe_sql(sql_query)
        if not is_safe:
            return {"success": False, "error": msg, "data": []}

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql_query))
                keys = result.keys()
                rows = [dict(zip(keys, row)) for row in result.fetchall()]
                return {"success": True, "error": None, "data": rows}
        except Exception as e:
            return {"success": False, "error": str(e), "data": []}

    def generate_and_execute(
        self, 
        system_prompt: str, 
        user_prompt: str, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Generates SQL via Groq LLM and executes it.
        Includes an automatic refinement sandbox loop if execution fails.
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "{user_input}")
        ])
        chain = prompt | self.llm | StrOutputParser()

        current_user_input = user_prompt
        attempt = 0

        while attempt < max_retries:
            attempt += 1
            print(f"\n⚡ Generating SQL (Attempt {attempt}/{max_retries})...")
            
            raw_response = chain.invoke({"user_input": current_user_input})
            
            # Extract SQL block from response
            sql_match = re.search(r"```sql\s*(.*?)\s*```", raw_response, re.DOTALL)
            sql_query = sql_match.group(1).strip() if sql_match else raw_response.strip()

            print(f"📌 Generated SQL:\n{sql_query}\n")

            # Execute query
            exec_result = self.execute_sql(sql_query)

            if exec_result["success"]:
                print("✅ Execution Succeeded!")
                return {
                    "sql": sql_query,
                    "data": exec_result["data"],
                    "attempts": attempt,
                    "status": "SUCCESS"
                }

            print(f"❌ Execution Failed: {exec_result['error']}")
            
            # Feed error back into refinement loop
            current_user_input = f"""
The previously generated SQL failed to execute.
Failed SQL:
{sql_query}

Database Error Message:
{exec_result['error']}

Please correct the SQL query to fix this exact error based on the original user question. Output ONLY the valid SQL query inside a markdown ```sql code block.
"""

        return {
            "sql": sql_query,
            "data": [],
            "error": exec_result["error"],
            "attempts": attempt,
            "status": "FAILED"
        }

    def generate_final_answer(self, question: str, data: List[Any]) -> str:
        """
        Passes the extracted database data back to the LLM to generate a natural language summary.
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "You are a business intelligence assistant. "
                "Answer the user's question accurately using ONLY the provided database results. "
                "Be concise, direct, and conversational. Do not mention technical terms like SQL or database schemas."
            )),
            ("user", "User Question: {question}\n\nRetrieved Data:\n{data}\n\nFinal Answer:")
        ])

        chain = prompt | self.llm | StrOutputParser()
        return chain.invoke({
            "question": question, 
            "data": str(data[:15])  # Cap results context window size if needed
        })