"""
feedback_store.py

Manages user feedback on query results. Incorrect results become test cases;
correct results become few-shot examples for future generation.

This is the flywheel that makes the system better over time.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from pathlib import Path


class FeedbackEntry(BaseModel):
    """A single piece of user feedback on a query result."""
    
    id: str
    query_id: str
    question: str
    generated_sql: Optional[str] = None
    data: List[Dict[str, Any]] = Field(default_factory=list)
    confidence_score: Optional[float] = None
    is_correct: bool
    user_comment: Optional[str] = None
    timestamp: str
    was_used_for_training: bool = False


class TestCase(BaseModel):
    """A test case generated from incorrect feedback."""
    
    id: str
    question: str
    generated_sql: str
    expected_error: Optional[str] = None
    error_reason: str
    created_from_feedback_id: str
    created_at: str
    run_count: int = 0
    fixed: bool = False
    fix_notes: Optional[str] = None


class FewShotExample(BaseModel):
    """A few-shot example generated from correct feedback."""
    
    id: str
    question: str
    generated_sql: str
    natural_language_answer: Optional[str] = None
    data_sample: List[Dict[str, Any]] = Field(default_factory=list)
    confidence_score: float
    created_from_feedback_id: str
    created_at: str
    usage_count: int = 0
    category: str = ""  # e.g., "simple_select", "join", "aggregation"


class FeedbackStore:
    """In-memory feedback store with file persistence."""

    def __init__(self, base_dir: str = "data"):
        base_path = Path(base_dir)
        if not base_path.is_absolute():
            project_root = Path(__file__).resolve().parents[1]
            self.base_dir = project_root / base_path
        else:
            self.base_dir = base_path
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.feedback_dir = self.base_dir / "feedback"
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        
        self.test_cases_file = self.feedback_dir / "test_cases.json"
        self.examples_file = self.feedback_dir / "few_shot_examples.json"
        self.feedback_file = self.feedback_dir / "feedback_log.json"
        
        # In-memory stores
        self.feedbacks: List[FeedbackEntry] = []
        self.test_cases: List[TestCase] = []
        self.few_shot_examples: List[FewShotExample] = []
        
        # Load from disk
        self._load()
    
    def _load(self):
        """Load feedback, test cases, and examples from disk."""
        if self.feedback_file.exists():
            try:
                with open(self.feedback_file, 'r') as f:
                    data = json.load(f)
                    self.feedbacks = [FeedbackEntry(**item) for item in data]
            except Exception as e:
                print(f"Error loading feedback: {e}")
        
        if self.test_cases_file.exists():
            try:
                with open(self.test_cases_file, 'r') as f:
                    data = json.load(f)
                    self.test_cases = [TestCase(**item) for item in data]
            except Exception as e:
                print(f"Error loading test cases: {e}")
        
        if self.examples_file.exists():
            try:
                with open(self.examples_file, 'r') as f:
                    data = json.load(f)
                    self.few_shot_examples = [FewShotExample(**item) for item in data]
            except Exception as e:
                print(f"Error loading few-shot examples: {e}")
    
    def _save(self):
        """Save feedback, test cases, and examples to disk."""
        try:
            with open(self.feedback_file, 'w') as f:
                json.dump([item.dict() for item in self.feedbacks], f, indent=2)
        except Exception as e:
            print(f"Error saving feedback: {e}")
        
        try:
            with open(self.test_cases_file, 'w') as f:
                json.dump([item.dict() for item in self.test_cases], f, indent=2)
        except Exception as e:
            print(f"Error saving test cases: {e}")
        
        try:
            with open(self.examples_file, 'w') as f:
                json.dump([item.dict() for item in self.few_shot_examples], f, indent=2)
        except Exception as e:
            print(f"Error saving few-shot examples: {e}")
    
    def add_feedback(
        self,
        feedback_id: str,
        query_id: str,
        question: str,
        is_correct: bool,
        generated_sql: Optional[str] = None,
        data: Optional[List[Dict[str, Any]]] = None,
        confidence_score: Optional[float] = None,
        user_comment: Optional[str] = None
    ) -> FeedbackEntry:
        """
        Add a feedback entry. If incorrect, automatically create a test case.
        If correct, automatically create a few-shot example.
        """
        self._load()
        entry = FeedbackEntry(
            id=feedback_id,
            query_id=query_id,
            question=question,
            generated_sql=generated_sql,
            data=data or [],
            confidence_score=confidence_score,
            is_correct=is_correct,
            user_comment=user_comment,
            timestamp=datetime.now().isoformat(),
            was_used_for_training=False
        )
        
        self.feedbacks.append(entry)
        
        # Generate test case or example based on feedback
        if not is_correct:
            self._create_test_case_from_feedback(entry)
        else:
            self._create_example_from_feedback(entry)
        
        self._save()
        return entry
    
    def _create_test_case_from_feedback(self, feedback: FeedbackEntry):
        """Create a test case from incorrect feedback."""
        import uuid
        
        test_case = TestCase(
            id=str(uuid.uuid4()),
            question=feedback.question,
            generated_sql=feedback.generated_sql or "",
            expected_error=None,
            error_reason=feedback.user_comment or "User marked as incorrect",
            created_from_feedback_id=feedback.id,
            created_at=datetime.now().isoformat(),
            run_count=0,
            fixed=False
        )
        
        self.test_cases.append(test_case)
        print(f"✅ Created test case from feedback: {test_case.id}")
    
    def _create_example_from_feedback(self, feedback: FeedbackEntry):
        """Create a few-shot example from correct feedback."""
        import uuid
        
        # Categorize based on SQL patterns
        category = self._categorize_sql(feedback.generated_sql or "")
        
        example = FewShotExample(
            id=str(uuid.uuid4()),
            question=feedback.question,
            generated_sql=feedback.generated_sql or "",
            data_sample=feedback.data[:5],  # Keep first 5 rows as sample
            confidence_score=feedback.confidence_score or 0.9,
            created_from_feedback_id=feedback.id,
            created_at=datetime.now().isoformat(),
            usage_count=0,
            category=category
        )
        
        self.few_shot_examples.append(example)
        print(f"✅ Created few-shot example from feedback: {example.id}")
    
    def _categorize_sql(self, sql: str) -> str:
        """Simple SQL categorization based on keywords."""
        sql_upper = sql.upper()
        
        if "JOIN" in sql_upper:
            return "join"
        elif "GROUP BY" in sql_upper:
            return "aggregation"
        elif "ORDER BY" in sql_upper:
            return "sorting"
        elif "WHERE" in sql_upper:
            return "filtering"
        else:
            return "simple_select"
    
    def get_test_cases(self, fixed: Optional[bool] = None) -> List[TestCase]:
        """Get test cases, optionally filtered by fixed status."""
        self._load()
        if fixed is None:
            return self.test_cases
        return [tc for tc in self.test_cases if tc.fixed == fixed]

    def get_few_shot_examples(self, category: Optional[str] = None) -> List[FewShotExample]:
        """Get few-shot examples, optionally filtered by category."""
        self._load()
        if category is None:
            return self.few_shot_examples
        return [ex for ex in self.few_shot_examples if ex.category == category]
    
    def mark_test_case_fixed(self, test_case_id: str, fix_notes: str = ""):
        """Mark a test case as fixed."""
        for tc in self.test_cases:
            if tc.id == test_case_id:
                tc.fixed = True
                tc.fix_notes = fix_notes
                self._save()
                return tc
        return None
    
    def increment_example_usage(self, example_id: str):
        """Increment usage count for a few-shot example."""
        for ex in self.few_shot_examples:
            if ex.id == example_id:
                ex.usage_count += 1
                self._save()
                return ex
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get feedback loop statistics."""
        self._load()
        correct_feedback = len([f for f in self.feedbacks if f.is_correct])
        incorrect_feedback = len([f for f in self.feedbacks if not f.is_correct])
        fixed_test_cases = len([tc for tc in self.test_cases if tc.fixed])

        return {
            "total_feedback": len(self.feedbacks),
            "correct_feedback": correct_feedback,
            "incorrect_feedback": incorrect_feedback,
            "total_test_cases": len(self.test_cases),
            "fixed_test_cases": fixed_test_cases,
            "unfixed_test_cases": len(self.test_cases) - fixed_test_cases,
            "total_few_shot_examples": len(self.few_shot_examples),
            "average_example_usage": sum(ex.usage_count for ex in self.few_shot_examples) / len(self.few_shot_examples) if self.few_shot_examples else 0
        }
    
    def export_test_cases_for_eval(self) -> List[Dict[str, Any]]:
        """Export unfixed test cases for evaluation suite."""
        return [
            {
                "test_id": tc.id,
                "question": tc.question,
                "generated_sql": tc.generated_sql,
                "error_reason": tc.error_reason,
                "error_expected": tc.expected_error
            }
            for tc in self.test_cases if not tc.fixed
        ]
    
    def export_few_shot_for_prompting(self, top_k: int = 5) -> List[Dict[str, Any]]:
        """Export top few-shot examples for use in prompt construction."""
        self._load()
        # Sort by usage count (most used first) to get high-quality examples
        sorted_examples = sorted(
            self.few_shot_examples,
            key=lambda ex: ex.usage_count,
            reverse=True
        )
        
        return [
            {
                "question": ex.question,
                "sql": ex.generated_sql,
                "answer": ex.natural_language_answer,
                "category": ex.category,
                "usage_count": ex.usage_count
            }
            for ex in sorted_examples[:top_k]
        ]
