"""
feedback_examples.py

Examples of how to use the feedback loop system programmatically.
These show common patterns for integrating feedback into your workflow.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pipeline.feedback_store import FeedbackStore, FeedbackEntry, TestCase, FewShotExample
from pipeline.pipeline_core import run_pipeline
import uuid
from datetime import datetime


# ============================================================================
# EXAMPLE 1: Adding feedback programmatically
# ============================================================================
def example_add_feedback():
    """Show how to add feedback entries manually."""
    print("\n" + "="*70)
    print("EXAMPLE 1: Adding Feedback Programmatically")
    print("="*70)
    
    store = FeedbackStore()
    
    # Simulate a query result
    question = "How many orders were placed in January 2024?"
    generated_sql = "SELECT COUNT(*) FROM orders WHERE DATE_PART('month', created_at) = 1"
    data = [{"count": 1523}]
    
    # Add feedback for a correct result
    feedback_correct = store.add_feedback(
        feedback_id=str(uuid.uuid4()),
        query_id=str(uuid.uuid4()),
        question=question,
        is_correct=True,
        generated_sql=generated_sql,
        data=data,
        confidence_score=0.95,
        user_comment="Exact match with expected results"
    )
    
    print(f"✅ Added correct feedback: {feedback_correct.id}")
    print(f"   - Few-shot example created")
    
    # Add feedback for an incorrect result
    question2 = "Show me the top 5 customers by revenue"
    generated_sql2 = "SELECT TOP 5 customer_id FROM orders"  # Wrong syntax
    
    feedback_incorrect = store.add_feedback(
        feedback_id=str(uuid.uuid4()),
        query_id=str(uuid.uuid4()),
        question=question2,
        is_correct=False,
        generated_sql=generated_sql2,
        confidence_score=0.42,
        user_comment="SQL syntax error - TOP not valid in PostgreSQL"
    )
    
    print(f"❌ Added incorrect feedback: {feedback_incorrect.id}")
    print(f"   - Test case created")
    print(f"\n📊 Store now has:")
    print(f"   - {len(store.feedbacks)} feedback entries")
    print(f"   - {len(store.few_shot_examples)} few-shot examples")
    print(f"   - {len(store.test_cases)} test cases")


# ============================================================================
# EXAMPLE 2: Getting statistics
# ============================================================================
def example_get_stats():
    """Show how to retrieve and analyze feedback statistics."""
    print("\n" + "="*70)
    print("EXAMPLE 2: Getting Feedback Statistics")
    print("="*70)
    
    store = FeedbackStore()
    stats = store.get_stats()
    
    print(f"\n📊 Feedback Statistics:")
    print(f"   Total feedback: {stats['total_feedback']}")
    print(f"   ✅ Correct: {stats['correct_feedback']}")
    print(f"   ❌ Incorrect: {stats['incorrect_feedback']}")
    
    if stats['total_feedback'] > 0:
        accuracy = (stats['correct_feedback'] / stats['total_feedback']) * 100
        print(f"   Accuracy: {accuracy:.1f}%")
    
    print(f"\n🧪 Test Cases:")
    print(f"   Total: {stats['total_test_cases']}")
    print(f"   Fixed: {stats['fixed_test_cases']}")
    print(f"   Unfixed: {stats['unfixed_test_cases']}")
    
    print(f"\n💡 Few-Shot Examples:")
    print(f"   Total: {stats['total_few_shot_examples']}")
    print(f"   Avg usage: {stats['average_example_usage']:.2f} times")


# ============================================================================
# EXAMPLE 3: Getting few-shot examples for prompting
# ============================================================================
def example_export_few_shot():
    """Show how to export examples for use in LLM prompts."""
    print("\n" + "="*70)
    print("EXAMPLE 3: Exporting Few-Shot Examples for Prompting")
    print("="*70)
    
    store = FeedbackStore()
    
    # Get top 5 examples (sorted by usage)
    examples = store.export_few_shot_for_prompting(top_k=5)
    
    print(f"\n📚 Top few-shot examples for prompting:")
    print(f"   Count: {len(examples)}")
    
    if examples:
        for i, ex in enumerate(examples, 1):
            print(f"\n   Example {i}:")
            print(f"   Question: {ex['question']}")
            print(f"   Category: {ex['category']}")
            print(f"   Usage: {ex['usage_count']} times")
            print(f"   SQL: {ex['sql'][:100]}...")
    else:
        print("   No examples yet. Run the system and mark results as correct!")
    
    # Build a prompt with these examples
    if examples:
        prompt = f"""You are a SQL expert. Here are examples of correct queries:

"""
        for i, ex in enumerate(examples, 1):
            prompt += f"""
Example {i}:
Question: {ex['question']}
SQL: {ex['sql']}
Category: {ex['category']}

"""
        
        prompt += """Now generate SQL for the user's question:"""
        
        print(f"\n✅ Sample prompt with examples:")
        print(prompt[:500] + "...")


# ============================================================================
# EXAMPLE 4: Getting test cases for eval suite
# ============================================================================
def example_export_test_cases():
    """Show how to export test cases for evaluation."""
    print("\n" + "="*70)
    print("EXAMPLE 4: Exporting Test Cases for Eval Suite")
    print("="*70)
    
    store = FeedbackStore()
    
    # Get unfixed test cases
    test_cases = store.export_test_cases_for_eval()
    
    print(f"\n🧪 Test cases from user feedback:")
    print(f"   Count: {len(test_cases)}")
    
    if test_cases:
        for i, tc in enumerate(test_cases[:3], 1):  # Show first 3
            print(f"\n   Test {i}:")
            print(f"   Question: {tc['question']}")
            print(f"   Error: {tc['error_reason']}")
            print(f"   SQL: {tc['generated_sql'][:80]}...")
    else:
        print("   No test cases yet. Mark incorrect results to build test suite!")
    
    # Show how to use in eval suite
    print(f"\n✅ Using in eval suite:")
    print("""
    for tc in test_cases:
        result = run_pipeline(tc['question'])
        
        # This test should be FIXED (no longer fail)
        assert result.generated_sql != tc['generated_sql'], \
               f"Bug still exists: {tc['test_id']}"
    """)


# ============================================================================
# EXAMPLE 5: Marking test cases as fixed
# ============================================================================
def example_mark_fixed():
    """Show how to mark test cases as fixed."""
    print("\n" + "="*70)
    print("EXAMPLE 5: Marking Test Cases as Fixed")
    print("="*70)
    
    store = FeedbackStore()
    
    # Get an unfixed test case
    unfixed = store.get_test_cases(fixed=False)
    
    if unfixed:
        tc = unfixed[0]
        print(f"\n🧪 Test case: {tc.question}")
        print(f"   Status: UNFIXED")
        
        # Mark as fixed
        fixed_tc = store.mark_test_case_fixed(
            tc.id,
            fix_notes="Fixed SQL syntax error - changed TOP to LIMIT"
        )
        
        print(f"✅ Marked as fixed!")
        print(f"   Fix notes: {fixed_tc.fix_notes}")
        
        # Check updated stats
        stats = store.get_stats()
        print(f"\n📊 Updated stats:")
        print(f"   Total test cases: {stats['total_test_cases']}")
        print(f"   Fixed: {stats['fixed_test_cases']}")
        print(f"   Unfixed: {stats['unfixed_test_cases']}")
    else:
        print("   No unfixed test cases to demonstrate with.")


# ============================================================================
# EXAMPLE 6: Categorizing by SQL pattern
# ============================================================================
def example_examples_by_category():
    """Show how to get examples organized by category."""
    print("\n" + "="*70)
    print("EXAMPLE 6: Getting Examples by Category")
    print("="*70)
    
    store = FeedbackStore()
    
    categories = ["simple_select", "join", "aggregation", "filtering", "sorting"]
    
    print(f"\n📚 Few-shot examples by category:")
    
    for category in categories:
        examples = store.get_few_shot_examples(category=category)
        print(f"   {category.upper()}: {len(examples)} examples")
        
        if examples:
            for ex in examples[:2]:  # Show first 2
                print(f"      - {ex.question[:50]}...")
    
    print(f"\n✅ Use cases:")
    print(f"   - Include JOIN examples when user asks about multiple tables")
    print(f"   - Include AGGREGATION examples for COUNT/SUM questions")
    print(f"   - Improve prompt relevance with category-specific examples")


# ============================================================================
# EXAMPLE 7: Building a continuous improvement workflow
# ============================================================================
def example_improvement_workflow():
    """Show a real workflow: get query -> collect feedback -> improve."""
    print("\n" + "="*70)
    print("EXAMPLE 7: Continuous Improvement Workflow")
    print("="*70)
    
    store = FeedbackStore()
    
    print("""
    🔄 Continuous Improvement Workflow:
    
    Day 1:
    ------
    1. Deploy system to production
    2. User asks: "Show customers from California"
    3. System generates: SELECT * FROM customers WHERE state = 'CA'
    4. User marks as ✅ Correct
       → Few-shot example created: (simple_select category)
    5. Another user asks: "Top products by revenue"
    6. System generates WRONG SQL
    7. User marks as ❌ Incorrect + explains error
       → Test case created: (for debugging)
    
    End of Day 1 Stats:
    -------------------
    • 15 queries run
    • 12 correct (80%)
    • 3 incorrect (20%)
    • 12 few-shot examples generated
    • 3 test cases generated
    
    Day 2:
    ------
    1. Eng team reviews test cases
    2. Finds bug: missing LIMIT clause
    3. Fixes SQL generator
    4. Test cases from Day 1 now pass ✅
    5. Next iteration of LLM prompt includes Day 1's examples
       → Better few-shot prompting
    6. System accuracy improves
    
    Results Over Time:
    ------------------
    Week 1: 75% accuracy, 20 test cases, 15 examples
    Week 2: 81% accuracy, 8 new test cases, 35 examples
    Week 3: 87% accuracy, 4 new test cases, 58 examples
    Week 4: 92% accuracy, 1 new test case, 89 examples
    
    🎯 The system gets better with EVERY user interaction!
    """)


# ============================================================================
# EXAMPLE 8: Export for analytics
# ============================================================================
def example_analytics_export():
    """Show how to export data for analytics tools."""
    print("\n" + "="*70)
    print("EXAMPLE 8: Exporting Data for Analytics")
    print("="*70)
    
    store = FeedbackStore()
    stats = store.get_stats()
    
    # Export for plotting/analysis
    analytics_data = {
        "timestamp": datetime.now().isoformat(),
        "total_feedback": stats["total_feedback"],
        "accuracy": (stats["correct_feedback"] / max(1, stats["total_feedback"])) * 100,
        "test_cases": stats["total_test_cases"],
        "test_case_fix_rate": (stats["fixed_test_cases"] / max(1, stats["total_test_cases"])) * 100,
        "examples": stats["total_few_shot_examples"],
        "example_usage": stats["average_example_usage"],
    }
    
    print(f"\n📊 Analytics snapshot:")
    for key, value in analytics_data.items():
        if isinstance(value, float):
            print(f"   {key}: {value:.2f}")
        else:
            print(f"   {key}: {value}")
    
    print(f"\n✅ Can export to:")
    print(f"   - CSV for Excel/Sheets")
    print(f"   - JSON for API/Dashboard")
    print(f"   - Database for time-series tracking")


# ============================================================================
# Run all examples
# ============================================================================
if __name__ == "__main__":
    print("\n🎯 FEEDBACK LOOP SYSTEM - EXAMPLES\n")
    
    try:
        example_add_feedback()
        example_get_stats()
        example_export_few_shot()
        example_export_test_cases()
        example_mark_fixed()
        example_examples_by_category()
        example_improvement_workflow()
        example_analytics_export()
        
        print("\n" + "="*70)
        print("✅ All examples completed!")
        print("="*70)
        print("\n📚 Next steps:")
        print("   1. Review data in data/feedback/")
        print("   2. Run Streamlit: streamlit run frontend/app.py")
        print("   3. Submit feedback and watch the flywheel spin!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
