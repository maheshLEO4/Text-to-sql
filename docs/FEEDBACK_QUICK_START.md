# 🎯 Feedback Loop - Quick Start Guide

## What Was Added

A complete feedback loop system that turns user interactions into system improvements:

### Files Created
- ✅ `pipeline/feedback_store.py` - Feedback storage and processing
- ✅ `docs/FEEDBACK_LOOP.md` - Comprehensive documentation
- ✅ API endpoints in `api/main.py` - Feedback submission and retrieval
- ✅ Streamlit UI in `frontend/app.py` - Feedback buttons and analytics dashboard

### Files Modified
- `api/main.py` - Added 4 feedback endpoints
- `frontend/app.py` - Added Feedback tab in results + Analytics dashboard

## How It Works

### User Marks Result as Correct ✅
```
User clicks: ✅ Correct
↓
System creates: FewShotExample
↓
Stored in: data/feedback/few_shot_examples.json
↓
Used to: Improve future SQL generation via prompts
```

### User Marks Result as Incorrect ❌
```
User clicks: ❌ Incorrect
User comment: "Query returned wrong row count"
↓
System creates: TestCase
↓
Stored in: data/feedback/test_cases.json
↓
Used to: Find and fix bugs in eval suite
```

## Running the System

### 1. Start FastAPI Backend (in one terminal)
```bash
uvicorn api.main:app --reload --port 8000
```

### 2. Start Streamlit Frontend (in another terminal)
```bash
streamlit run frontend/app.py
```

### 3. Use the System
- Ask questions in the "Query" tab
- View results
- Provide feedback (✅ or ❌)
- Check "Feedback Analytics" tab to see the flywheel in action

## Feedback Analytics Dashboard

Three tabs in the "Feedback Analytics" section:

### 📊 Statistics
- Total feedback count
- Correct vs incorrect split
- Test cases created
- Few-shot examples generated

### 🧪 Test Cases
- List of incorrect results marked by users
- Shows question, SQL, and error reason
- Used to create regression test suite

### 💡 Few-Shot Examples
- List of correct results marked by users
- Organized by category (join, aggregation, etc.)
- Shows usage count (how many times used in prompts)
- Higher usage = higher quality examples

## Key Endpoints

```bash
# Submit feedback
POST /v1/feedback
{
  "query_id": "uuid",
  "is_correct": true,
  "user_comment": "Perfect!"
}

# Get statistics
GET /v1/feedback/stats

# Get test cases
GET /v1/feedback/test-cases

# Get few-shot examples
GET /v1/feedback/few-shot-examples?top_k=5
```

## Data Locations

Feedback data is stored in JSON files in `data/feedback/`:
```
data/
├── feedback/
│   ├── feedback_log.json          # Raw user feedback
│   ├── test_cases.json            # Unfixed bugs
│   └── few_shot_examples.json     # Correct examples
```

## The Flywheel Effect

```
1. User gets result and marks it ✅ Correct
   ↓
2. System creates FewShotExample with SQL, question, category
   ↓
3. Example added to few_shot_examples.json
   ↓
4. Next time prompt constructor builds LLM prompt:
   - Fetches top few-shot examples
   - Includes them in prompt
   ↓
5. LLM uses these examples for in-context learning
   ↓
6. Future SQL generation improves
   ↓
7. More correct results
   ↓
8. More positive feedback
   ↓
9. More and better examples
   ↓
10. LOOP: System gets smarter with each interaction
```

## Integration with Eval Suite

Export test cases for automated testing:

```python
from pipeline.feedback_store import FeedbackStore

store = FeedbackStore()

# Get unfixed test cases from user feedback
test_cases = store.export_test_cases_for_eval()

# Use in your eval suite:
for tc in test_cases:
    result = run_pipeline(tc["question"])
    assert result.generated_sql != tc["generated_sql"], f"Test {tc['test_id']} failed"
```

## Integration with Prompt Construction

Use few-shot examples in prompt:

```python
from pipeline.feedback_store import FeedbackStore

store = FeedbackStore()

# Get top examples (sorted by usage/quality)
examples = store.export_few_shot_for_prompting(top_k=5)

# Build prompt with examples
system_prompt = f"""
You are a SQL expert. Here are examples of correct queries:

{format_examples(examples)}

Now generate SQL for the user's question.
"""
```

## Example Workflow

1. **Morning**: You have 50 queries from users
2. **Throughout day**: Users mark results as correct/incorrect
   - 40 marked correct → 40 few-shot examples created
   - 10 marked incorrect → 10 test cases created
3. **End of day**: Check Feedback Analytics
   - 40 new examples (improve future generation)
   - 10 bugs to fix (improve reliability)
   - Avg example usage: 1.2 (shows examples are being used)
4. **Next iteration**: 
   - Test suite includes the 10 bugs
   - LLM prompts include the 40 examples
   - System is demonstrably better

## Customization

### Change Feedback Storage Location
```python
# Use different directory
store = FeedbackStore(base_dir="custom/feedback/location")
```

### Add Custom Categorization
```python
# In FeedbackStore._categorize_sql()
def _categorize_sql(self, sql: str) -> str:
    # Add your own categorization logic
    if "WINDOW" in sql.upper():
        return "window_function"
    # ...
```

### Export for Training
```python
# Get all correct examples with confidence > 0.9
high_quality = [ex for ex in store.few_shot_examples 
                if ex.confidence_score > 0.9]

# Use for fine-tuning LLM
fine_tune_data = [
    {"input": ex.question, "output": ex.generated_sql}
    for ex in high_quality
]
```

## Monitoring

Check feedback loop health:
```python
from pipeline.feedback_store import FeedbackStore

store = FeedbackStore()
stats = store.get_stats()

print(f"✅ Correct: {stats['correct_feedback']}")
print(f"❌ Incorrect: {stats['incorrect_feedback']}")
print(f"Accuracy: {stats['correct_feedback'] / (stats['correct_feedback'] + stats['incorrect_feedback']) * 100:.1f}%")
print(f"Test cases fixed: {stats['fixed_test_cases']} / {stats['total_test_cases']}")
```

## Next Steps

1. Run the system and get user feedback
2. Monitor the Feedback Analytics dashboard
3. Export test cases to eval suite
4. Use few-shot examples in prompts
5. Watch accuracy improve with each iteration

---

**That's the flywheel!** Each interaction makes the system smarter. 🚀
