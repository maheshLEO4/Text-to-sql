# 🎯 Feedback Loop System - The Flywheel

## Overview

The feedback loop is the engine that makes the Text-to-SQL system continuously improve. Users provide feedback on query results, which is automatically processed to:

1. **Correct Results ✅** → Become **few-shot examples** for better future generation
2. **Incorrect Results ❌** → Become **test cases** to find and fix bugs

This creates a virtuous cycle where using the system makes it smarter.

## Architecture

### Components

#### 1. **Feedback Store** (`pipeline/feedback_store.py`)
Manages all feedback data and generates training materials:

- **FeedbackEntry**: Individual piece of user feedback
- **TestCase**: Generated from incorrect feedback (for debugging)
- **FewShotExample**: Generated from correct feedback (for prompting)

**Key Methods:**
- `add_feedback()` - Record user feedback and auto-generate test cases/examples
- `get_test_cases()` - Retrieve unfixed test cases
- `get_few_shot_examples()` - Retrieve examples by category
- `export_test_cases_for_eval()` - Format for evaluation suite
- `export_few_shot_for_prompting()` - Format for LLM prompts

#### 2. **API Endpoints** (`api/main.py`)

**Feedback Endpoints:**
```
POST   /v1/feedback                    # Submit user feedback
GET    /v1/feedback/stats              # Get feedback statistics
GET    /v1/feedback/test-cases         # Get unfixed test cases
GET    /v1/feedback/few-shot-examples  # Get few-shot examples
```

#### 3. **Frontend** (`frontend/app.py`)
Streamlit interface with:
- Feedback buttons (✅ Correct / ❌ Incorrect)
- Feedback tab in results view
- "Feedback Analytics" dashboard
- Statistics and metrics tracking

## User Workflow

### Step 1: User Submits Query
```
User: "How many customers are from New York?"
```

### Step 2: System Returns Result
- Generated SQL
- Query results
- Confidence score
- Explanation

### Step 3: User Provides Feedback

**Scenario A: Result is Correct ✅**
```
User clicks: ✅ Correct
System: "Thank you! Added to few-shot examples to improve future queries."

What happens:
1. Feedback recorded
2. FewShotExample created with:
   - Question
   - Generated SQL
   - Category (join, aggregation, etc.)
   - Confidence score
3. Example saved to: data/feedback/few_shot_examples.json
```

**Scenario B: Result is Incorrect ❌**
```
User clicks: ❌ Incorrect
User enters: "Query returned wrong row count"
System: "Feedback noted! Added as test case to fix in next iteration."

What happens:
1. Feedback recorded with user comment
2. TestCase created with:
   - Question
   - Generated SQL
   - Error reason
   - Status: unfixed
3. Test case saved to: data/feedback/test_cases.json
```

## Data Storage

### Directory Structure
```
data/
├── feedback/
│   ├── feedback_log.json          # All user feedback entries
│   ├── test_cases.json            # Test cases (unfixed bugs)
│   └── few_shot_examples.json     # Few-shot examples for prompting
└── schema_cache.json
```

### Example: feedback_log.json
```json
[
  {
    "id": "uuid-123",
    "query_id": "query-456",
    "question": "How many customers are from New York?",
    "generated_sql": "SELECT COUNT(*) FROM customers WHERE city = 'New York'",
    "data": [...],
    "confidence_score": 0.92,
    "is_correct": true,
    "user_comment": null,
    "timestamp": "2025-01-15T10:30:00",
    "was_used_for_training": false
  }
]
```

## Integration Points

### 1. **Eval Suite Integration**
Export test cases for automated testing:

```python
from pipeline.feedback_store import FeedbackStore

store = FeedbackStore()
test_cases = store.export_test_cases_for_eval()
# Use these as regression test suite
```

### 2. **Prompt Construction Integration**
Use few-shot examples to improve generation:

```python
from pipeline.feedback_store import FeedbackStore

store = FeedbackStore()
# Get top-5 examples, preferring most-used ones
examples = store.export_few_shot_for_prompting(top_k=5)

# Add to prompt:
prompt = f"""
Here are examples of correct SQL queries:
{examples}

Now generate SQL for: {user_question}
"""
```

### 3. **Analytics Pipeline Integration**
Track system improvement over time:

```python
from pipeline.feedback_store import FeedbackStore

store = FeedbackStore()
stats = store.get_stats()

print(f"Total feedback: {stats['total_feedback']}")
print(f"Test cases fixed: {stats['fixed_test_cases']} / {stats['total_test_cases']}")
print(f"Example usage: {stats['average_example_usage']} avg per example")
```

## Key Features

### Auto-Categorization
Few-shot examples are automatically categorized:
- `simple_select` - Basic SELECT queries
- `join` - Multi-table joins
- `aggregation` - GROUP BY, COUNT, SUM, etc.
- `filtering` - WHERE clauses
- `sorting` - ORDER BY

### Usage Tracking
- Each few-shot example tracks how many times it was used
- Examples are ranked by usage for better prompting
- Helps identify which patterns are most useful

### Fix Tracking
- Test cases track whether they've been fixed
- `mark_test_case_fixed()` documents the fix
- Supports regression testing

## Dashboard Metrics

The Feedback Analytics tab shows:

```
Total Feedback:     42
✅ Correct:         31 (74%)
❌ Incorrect:       11 (26%)
─────────────────────────────
Test Cases:         11
  Fixed:            2
  Unfixed:          9

Few-Shot Examples:  31
  Avg Usage:        2.1 times
```

## Workflow: From Feedback to Improvement

```
┌─────────────┐
│   User      │
│  Feedback   │
└──────┬──────┘
       │
       ├──[Correct]────→ FewShotExample
       │                     │
       │                     └──→ Added to prompts
       │                         ↓
       │                     Better future queries
       │
       └──[Incorrect]──→ TestCase
                            │
                            └──→ Added to eval suite
                                ↓
                            Identify & fix bugs
```

## Commands

### View Feedback Stats
```bash
curl http://localhost:8000/v1/feedback/stats
```

### Get Unfixed Test Cases
```bash
curl http://localhost:8000/v1/feedback/test-cases
```

### Get Few-Shot Examples
```bash
curl "http://localhost:8000/v1/feedback/few-shot-examples?top_k=10"
```

### Get Examples by Category
```bash
curl "http://localhost:8000/v1/feedback/few-shot-examples?category=join"
```

### Submit Feedback
```bash
curl -X POST http://localhost:8000/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "query-123",
    "is_correct": true,
    "user_comment": "Perfect result!"
  }'
```

## Best Practices

1. **Mark Results Accurately**
   - ✅ Only mark genuinely correct results
   - ❌ Be specific about what was wrong

2. **Provide Comments**
   - For incorrect results, explain what went wrong
   - Helps with debugging and fix implementation

3. **Regular Review**
   - Check Feedback Analytics dashboard weekly
   - Monitor how examples are being used
   - Track test case fix rate

4. **Use Examples in Prompts**
   - Include high-usage examples in LLM prompts
   - Categories help organize by complexity
   - Confidence scores indicate quality

## Future Enhancements

1. **Automated Analysis**
   - Cluster similar incorrect queries
   - Suggest common patterns to fix

2. **Feedback Quality Metrics**
   - Track feedback accuracy
   - Identify high-quality feedback providers

3. **Active Learning**
   - Query generation focused on hard cases
   - Prioritize ambiguous results for feedback

4. **Model Updates**
   - Fine-tune LLM with few-shot examples
   - Retrain guardrails with test cases

5. **Persistence**
   - Move from JSON to database (PostgreSQL/SQLite)
   - Enable cross-session learning
   - Support distributed teams

## File Locations

- **Feedback Store**: `pipeline/feedback_store.py`
- **Feedback Data**: `data/feedback/`
- **API Endpoints**: `api/main.py` (lines with `/v1/feedback`)
- **Frontend**: `frontend/app.py` (Feedback tab and Analytics tab)

---

**The flywheel effect**: As users provide feedback, the system generates examples and test cases. These improve the system. Improved results lead to more correct feedback. More correct feedback means more and better examples. Better examples make the system even more accurate. And the cycle continues, with each iteration making the system stronger.
