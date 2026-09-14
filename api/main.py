"""
api/main.py

Phase 4, Step 1: API endpoints.

Exposes the Text-to-SQL pipeline over HTTP:
  POST /v1/query    - ask a natural language question, get SQL + results + confidence
  GET  /v1/schema    - inspect the current database schema
  GET  /v1/history   - see past queries run in this session

Run locally with:
    uvicorn api.main:app --reload --port 8000

History is stored in-memory for now (a plain list). This is intentional at
this stage — Phase 4 Step 3 (feedback loop) will decide whether it needs to
become persistent (e.g. a small SQLite/Postgres table) once we know what
shape the feedback data needs to take.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Make sibling package folders importable
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_THIS_DIR)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from pipeline.pipeline_core import run_pipeline, PipelineResult
from pipeline.feedback_store import FeedbackStore
from ingestion.schema_extractor import SchemaExtractor

# Initialize feedback store
feedback_store = FeedbackStore()

app = FastAPI(
    title="Text-to-SQL API",
    description="Natural language to SQL with guardrails, hallucination detection, and confidence scoring.",
    version="0.1.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# In-memory history store
# ---------------------------------------------------------------------------
class HistoryEntry(BaseModel):
    id: str
    question: str
    timestamp: str
    result: PipelineResult


_HISTORY: List[HistoryEntry] = []


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural language question to answer.")
    db_url: Optional[str] = Field(None, description="Optional PostgreSQL connection string for this request.")


class SchemaRequest(BaseModel):
    db_url: Optional[str] = Field(None, description="Optional PostgreSQL connection string for this request.")


class QueryResponse(BaseModel):
    id: str
    result: PipelineResult


class SchemaResponse(BaseModel):
    tables: List[str]
    formatted_schema: str


class HistoryResponse(BaseModel):
    count: int
    history: List[HistoryEntry]


# ---------------------------------------------------------------------------
# Feedback Models
# ---------------------------------------------------------------------------
class FeedbackRequest(BaseModel):
    query_id: str = Field(..., description="ID of the query being feedbacked on")
    is_correct: bool = Field(..., description="Whether the result was correct")
    user_comment: Optional[str] = Field(None, description="User's feedback comment")


class FeedbackResponse(BaseModel):
    feedback_id: str
    message: str
    test_case_created: bool = False
    example_created: bool = False


class FeedbackStatsResponse(BaseModel):
    total_feedback: int
    correct_feedback: int
    incorrect_feedback: int
    total_test_cases: int
    fixed_test_cases: int
    total_few_shot_examples: int


def validate_database_url(db_url: str) -> str:
    """Allow only PostgreSQL URLs and never persist or return the credential."""
    parsed = urlparse(db_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"} or not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="Only a valid PostgreSQL/Supabase connection string is supported.",
        )
    return db_url


def resolve_database_url(db_url: Optional[str]) -> str:
    """Use a supplied connection or the server-configured demo database."""
    if db_url:
        return validate_database_url(db_url)

    demo_db_url = os.getenv("DATABASE_URL")
    if not demo_db_url:
        raise HTTPException(status_code=500, detail="No demo database is configured on the backend.")
    return validate_database_url(demo_db_url)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/v1/query", response_model=QueryResponse)
def post_query(request: QueryRequest) -> QueryResponse:
    """
    Runs a natural language question through the full pipeline and returns
    the generated SQL, execution results, natural language answer, and
    confidence report. Also records the interaction in session history.
    """
    try:
        result = run_pipeline(
            user_question=request.question,
            db_url=resolve_database_url(request.db_url),
        )
    except Exception as e:
        # Anything that reaches here is an unexpected internal failure
        # (e.g. missing API keys, DB connection errors) rather than an
        # expected pipeline outcome, which run_pipeline already reports
        # via `status` without raising.
        raise HTTPException(status_code=500, detail=f"Pipeline execution error: {str(e)}")

    entry = HistoryEntry(
        id=str(uuid.uuid4()),
        question=request.question,
        timestamp=datetime.now(timezone.utc).isoformat(),
        result=result,
    )
    _HISTORY.append(entry)

    return QueryResponse(id=entry.id, result=result)


@app.post("/v1/schema", response_model=SchemaResponse)
def get_schema(request: SchemaRequest) -> SchemaResponse:
    """Returns the current database schema (tables + formatted context string)."""
    db_url = resolve_database_url(request.db_url)

    try:
        extractor = SchemaExtractor(db_url)
        full_schema = extractor.extract_full_schema()
        formatted = extractor.format_schema_for_prompt(full_schema)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schema extraction error: {str(e)}")

    return SchemaResponse(tables=list(full_schema.keys()), formatted_schema=formatted)


@app.get("/v1/history", response_model=HistoryResponse)
def get_history(limit: Optional[int] = None) -> HistoryResponse:
    """
    Returns past queries run in this session, most recent first.
    Pass `?limit=N` to cap how many entries come back.
    """
    ordered = list(reversed(_HISTORY))
    if limit is not None:
        ordered = ordered[:limit]
    return HistoryResponse(count=len(_HISTORY), history=ordered)


@app.get("/health")
def health() -> Dict[str, str]:
    """Basic liveness check."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Feedback Loop Endpoints (Phase 4, Step 3 - The Flywheel)
# ---------------------------------------------------------------------------
@app.post("/v1/feedback", response_model=FeedbackResponse)
def post_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Accept user feedback on a query result.
    
    - Incorrect results become TEST CASES for the eval suite
    - Correct results become FEW-SHOT EXAMPLES for prompt construction
    
    This creates the flywheel: users help improve the system as they use it.
    """
    # Find the query in history
    query_entry = None
    for entry in _HISTORY:
        if entry.id == request.query_id:
            query_entry = entry
            break
    
    if not query_entry:
        raise HTTPException(status_code=404, detail=f"Query {request.query_id} not found in history.")
    
    # Add feedback to store
    feedback_id = str(uuid.uuid4())
    feedback = feedback_store.add_feedback(
        feedback_id=feedback_id,
        query_id=request.query_id,
        question=query_entry.question,
        is_correct=request.is_correct,
        generated_sql=query_entry.result.generated_sql,
        data=query_entry.result.data,
        confidence_score=query_entry.result.confidence_report.composite_confidence_score if query_entry.result.confidence_report else None,
        user_comment=request.user_comment
    )
    
    message = ""
    test_case_created = False
    example_created = False
    
    if request.is_correct:
        message = f"✅ Thank you! Result marked as correct. Added to few-shot examples to improve future queries."
        example_created = True
    else:
        message = f"❌ Feedback noted! This has been added as a test case to fix in the next iteration."
        test_case_created = True
    
    return FeedbackResponse(
        feedback_id=feedback_id,
        message=message,
        test_case_created=test_case_created,
        example_created=example_created
    )


@app.get("/v1/feedback/stats", response_model=FeedbackStatsResponse)
def get_feedback_stats() -> FeedbackStatsResponse:
    """
    Get statistics on the feedback loop.
    Shows how many test cases and examples have been generated.
    """
    stats = feedback_store.get_stats()
    
    return FeedbackStatsResponse(
        total_feedback=stats["total_feedback"],
        correct_feedback=stats["correct_feedback"],
        incorrect_feedback=stats["incorrect_feedback"],
        total_test_cases=stats["total_test_cases"],
        fixed_test_cases=stats["fixed_test_cases"],
        total_few_shot_examples=stats["total_few_shot_examples"]
    )


@app.get("/v1/feedback/test-cases")
def get_test_cases(fixed: Optional[bool] = None) -> Dict[str, Any]:
    """
    Get unfixed test cases for evaluation suite.
    These are queries that users marked as incorrect, ready to be debugged and fixed.
    """
    test_cases = feedback_store.get_test_cases(fixed=fixed)
    
    return {
        "count": len(test_cases),
        "test_cases": [
            {
                "test_id": tc.id,
                "question": tc.question,
                "generated_sql": tc.generated_sql,
                "error_reason": tc.error_reason,
                "created_at": tc.created_at,
                "fixed": tc.fixed
            }
            for tc in test_cases
        ]
    }


@app.get("/v1/feedback/few-shot-examples")
def get_few_shot_examples(category: Optional[str] = None, top_k: int = 5) -> Dict[str, Any]:
    """
    Get few-shot examples for prompt construction.
    These are queries users marked as correct, used to improve future generation via LLM prompting.
    """
    if category is None:
        examples = feedback_store.few_shot_examples[:top_k]
    else:
        examples = feedback_store.get_few_shot_examples(category=category)[:top_k]
    
    return {
        "count": len(examples),
        "examples": [
            {
                "question": ex.question,
                "sql": ex.generated_sql,
                "category": ex.category,
                "confidence": ex.confidence_score,
                "usage_count": ex.usage_count
            }
            for ex in examples
        ]
    }
