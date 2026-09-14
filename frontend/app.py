"""
Streamlit frontend for Text-to-SQL pipeline.

Provides an interactive web interface to:
  - Ask natural language questions
  - View generated SQL
  - See query results
  - Check confidence scores
  - Review query history
"""

import streamlit as st
import requests
import json
import os
from datetime import datetime
from typing import Dict, Any, List

# Configuration
try:
    cloud_api_base_url = st.secrets.get("API_BASE_URL")
except Exception:
    cloud_api_base_url = None

API_BASE_URL = (cloud_api_base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
QUERY_ENDPOINT = f"{API_BASE_URL}/v1/query"
SCHEMA_ENDPOINT = f"{API_BASE_URL}/v1/schema"
HEALTH_ENDPOINT = f"{API_BASE_URL}/health"
FEEDBACK_ENDPOINT = f"{API_BASE_URL}/v1/feedback"
FEEDBACK_STATS_ENDPOINT = f"{API_BASE_URL}/v1/feedback/stats"
FEEDBACK_TEST_CASES_ENDPOINT = f"{API_BASE_URL}/v1/feedback/test-cases"
FEEDBACK_EXAMPLES_ENDPOINT = f"{API_BASE_URL}/v1/feedback/few-shot-examples"

# Page config
st.set_page_config(
    page_title="Text-to-SQL",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS styling
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 16px;
        font-weight: bold;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        padding: 12px;
        border-radius: 4px;
        margin: 10px 0;
    }
    .error-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
        padding: 12px;
        border-radius: 4px;
        margin: 10px 0;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        color: #856404;
        padding: 12px;
        border-radius: 4px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "query_history" not in st.session_state:
    st.session_state.query_history = []
if "current_response" not in st.session_state:
    st.session_state.current_response = None
if "feedback_status" not in st.session_state:
    st.session_state.feedback_status = {}
if "db_url" not in st.session_state:
    st.session_state.db_url = ""
if "readonly_acknowledged" not in st.session_state:
    st.session_state.readonly_acknowledged = False
if "use_demo_database" not in st.session_state:
    st.session_state.use_demo_database = True
if "schema_connection_key" not in st.session_state:
    st.session_state.schema_connection_key = None
if "schema_data" not in st.session_state:
    st.session_state.schema_data = None


def call_api(endpoint: str, method: str = "GET", data: Dict[str, Any] = None) -> Dict[str, Any]:
    """Make API call and handle errors."""
    try:
        timeout_seconds = 120
        if method == "GET":
            response = requests.get(endpoint, timeout=timeout_seconds)
        else:
            response = requests.post(endpoint, json=data, timeout=timeout_seconds)

        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to API. Is the server running at http://127.0.0.1:8000?"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "API request timed out."}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"API error: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}


@st.cache_data(ttl=30, show_spinner=False)
def backend_is_healthy(endpoint: str) -> bool:
    """Cache the public health check to avoid a request on every rerun."""
    return call_api(endpoint)["success"]


def display_result(result: Dict[str, Any], query_id: str = ""):
    """Display pipeline result in a structured format."""
    status = result.get("status", "UNKNOWN")
    
    # Status indicator
    if status == "SUCCESS":
        st.success(f"✅ Query executed successfully!")
    elif status == "AMBIGUOUS":
        st.warning(f"⚠️ Query is ambiguous")
    elif status == "GUARDRAIL_BLOCKED":
        st.error(f"🚫 Query blocked by security guardrails")
    elif status == "EXECUTION_FAILED":
        st.error(f"❌ Query execution failed")
    else:
        st.error(f"⚠️ {status}")
    
    # Tabs for different result sections
    tab1, tab2, tab_prompt, tab3, tab4, tab5, tab6 = st.tabs(["Results", "SQL", "Constructed Prompt", "Confidence", "Details", "Error", "Feedback"])
    
    with tab1:
        st.subheader("Query Results")
        if result.get("data"):
            st.dataframe(result["data"], use_container_width=True)
            st.info(f"📊 Row count: {result.get('row_count', 0)}")
        else:
            st.info("No data returned")
        
        if result.get("natural_language_answer"):
            st.subheader("Natural Language Answer")
            st.write(result["natural_language_answer"])
    
    with tab2:
        st.subheader("Generated SQL")
        if result.get("generated_sql"):
            st.code(result["generated_sql"], language="sql")
        else:
            st.info("No SQL generated")
        
        if result.get("explanation"):
            st.subheader("Explanation")
            st.write(result["explanation"])

    with tab_prompt:
        st.subheader("📋 Constructed LLM Prompt")
        few_count = result.get("few_shots_count", 0)
        if few_count > 0:
            st.success(f"💡 {few_count} Few-Shot Examples Loaded into Prompt from Feedback Store!")
        else:
            st.info("ℹ️ 0 Few-Shot Examples loaded (Mark results as '✅ Correct' in the Feedback tab to add few-shot examples).")
        
        if result.get("constructed_prompt"):
            st.code(result["constructed_prompt"], language="markdown")
        else:
            st.info("No constructed prompt available.")
    
    with tab3:
        st.subheader("Confidence Report")
        if result.get("confidence_report"):
            conf_report = result["confidence_report"]
            st.json(conf_report)
        else:
            st.info("No confidence report available")
    
    with tab4:
        st.subheader("Query Details")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Question:**")
            st.write(result.get("question", "N/A"))
            
            st.write("**Filtered Tables:**")
            if result.get("filtered_tables"):
                for table in result["filtered_tables"]:
                    st.write(f"  • {table}")
            else:
                st.write("None")
        
        with col2:
            st.write("**Status:**")
            st.write(result.get("status", "N/A"))
            
            if result.get("ambiguity"):
                st.write("**Ambiguity Details:**")
                st.json(result["ambiguity"])
    
    with tab5:
        if result.get("error_message"):
            st.error(result["error_message"])
        elif result.get("guardrail_rejection_reason"):
            st.error(f"**Guardrail Rejection:**\n{result['guardrail_rejection_reason']}")
        else:
            st.info("No errors")
    
    with tab6:
        st.subheader("📝 Help Improve the System!")
        st.markdown("""
        Your feedback helps the system learn and improve over time:
        
        - **Correct ✅** → Becomes a few-shot example for better future queries
        - **Incorrect ❌** → Becomes a test case to fix and improve
        """)

        # Check if feedback was already recorded for this query_id
        fb_record = st.session_state.feedback_status.get(query_id)
        if fb_record:
            if fb_record.get("is_correct"):
                st.success(f"✅ {fb_record['message']}")
            else:
                st.warning(f"❌ {fb_record['message']}")
        else:
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("✅ Correct", key=f"correct_{query_id}", use_container_width=True):
                    feedback_result = call_api(
                        FEEDBACK_ENDPOINT,
                        method="POST",
                        data={
                            "query_id": query_id,
                            "is_correct": True,
                            "user_comment": "User marked as correct"
                        }
                    )
                    if feedback_result["success"]:
                        msg = feedback_result["data"].get("message", "Feedback recorded!")
                        st.session_state.feedback_status[query_id] = {"message": msg, "is_correct": True}
                        st.rerun()
                    else:
                        st.error(feedback_result["error"])
            
            with col2:
                if st.button("❌ Incorrect", key=f"incorrect_{query_id}", use_container_width=True):
                    st.session_state[f"show_comment_{query_id}"] = not st.session_state.get(f"show_comment_{query_id}", False)
            
            if st.session_state.get(f"show_comment_{query_id}"):
                comment = st.text_area(
                    "What was wrong with this result?",
                    placeholder="e.g., 'Query returned wrong number of rows', 'SQL syntax error', etc.",
                    key=f"comment_input_{query_id}"
                )
                
                if st.button("Send Feedback", key=f"send_feedback_{query_id}"):
                    feedback_result = call_api(
                        FEEDBACK_ENDPOINT,
                        method="POST",
                        data={
                            "query_id": query_id,
                            "is_correct": False,
                            "user_comment": comment
                        }
                    )
                    if feedback_result["success"]:
                        msg = feedback_result["data"].get("message", "Feedback recorded!")
                        st.session_state.feedback_status[query_id] = {"message": msg, "is_correct": False}
                        st.session_state[f"show_comment_{query_id}"] = False
                        st.rerun()
                    else:
                        st.error(feedback_result["error"])



# Header
st.title("🔍 Text-to-SQL Query Engine")
st.markdown("Convert natural language questions to SQL queries with AI-powered guardrails and confidence scoring.")

# Sidebar
with st.sidebar:
    st.header("Database Connection")
    st.checkbox(
        "Use demo database",
        key="use_demo_database",
        help="Uses the database configured privately on the backend.",
    )
    if st.session_state.use_demo_database:
        st.info("Demo mode uses the backend's configured DATABASE_URL.")
        st.session_state.db_url = ""
    else:
        st.warning(
            "Create a dedicated database role with SELECT-only privileges before connecting. "
            "Never use your Supabase owner or service-role credentials."
        )
        db_url_input = st.text_input(
            "Supabase PostgreSQL connection string",
            type="password",
            placeholder="postgresql://readonly_user:password@.../postgres",
            key="db_url_input",
        )
        st.checkbox(
            "I am using a dedicated SELECT-only database role.",
            key="readonly_acknowledged",
        )
        if db_url_input and st.session_state.readonly_acknowledged:
            st.session_state.db_url = db_url_input.strip()
        else:
            st.session_state.db_url = ""

    if st.session_state.use_demo_database or st.session_state.db_url:
        st.success("Connection details ready for this session.")
    else:
        st.info("Enter a connection string and confirm the SELECT-only role to begin.")

    st.markdown("---")
    with st.expander("How it works"):
        st.markdown(
            "Schema extraction → SQL generation → read-only guardrails → "
            "sandboxed execution → confidence checks."
        )
        st.caption("Results can be marked correct or incorrect to improve future prompts.")
    
    st.markdown("---")
    st.markdown("**API Status:**")
    if backend_is_healthy(HEALTH_ENDPOINT):
        st.success("✅ API Connected")
    else:
        st.error("❌ API Disconnected")

# Main tabs
main_tab1, main_tab2, main_tab3 = st.tabs(["Query", "Schema", "Feedback Analytics"])

with main_tab1:
    demo_questions = [
        "How many customers are from New York?",
        "What is the total number of orders?",
        "List the top 5 products with the highest unit price.",
        "Which products have more than 50 units in stock?",
    ]
    if st.session_state.use_demo_database:
        demo_question = st.selectbox(
            "Demo questions",
            ["Choose a sample question"] + demo_questions,
        )
        if st.button("Use question", disabled=demo_question == "Choose a sample question"):
            st.session_state.question_input = demo_question
            st.rerun()

    col1, col2 = st.columns([3, 1])
    
    with col1:
        question = st.text_input(
            "Ask your question:",
            placeholder="e.g., 'How many customers are from New York?'",
            key="question_input"
        )
    
    with col2:
        submit_button = st.button("🚀 Execute", use_container_width=True)
    
    if submit_button and question and not st.session_state.use_demo_database and not st.session_state.db_url:
        st.error("Connect a database with a confirmed SELECT-only role first.")
    elif submit_button and question:
        with st.spinner("⏳ Processing query through pipeline..."):
            result = call_api(
                QUERY_ENDPOINT,
                method="POST",
                data={
                    "question": question,
                    **({"db_url": st.session_state.db_url} if st.session_state.db_url else {}),
                },
            )
            
            if result["success"]:
                response_data = result["data"]
                query_id = response_data.get("id", "")
                
                st.session_state.current_response = response_data
                
                # Add to session history
                st.session_state.query_history.append({
                    "id": query_id,
                    "timestamp": datetime.now().isoformat(),
                    "question": question,
                    "status": response_data.get("result", {}).get("status", "UNKNOWN"),
                    "response": response_data
                })
            else:
                st.error(result["error"])

    # Display current response if available
    if st.session_state.get("current_response"):
        resp = st.session_state["current_response"]
        display_result(resp.get("result", {}), query_id=resp.get("id", ""))

    
    # Query history
    if st.session_state.query_history:
        st.markdown("---")
        st.subheader("📜 Session History")
        
        for idx, entry in enumerate(reversed(st.session_state.query_history)):
            with st.expander(f"Query {len(st.session_state.query_history) - idx}: {entry['question'][:50]}..."):
                st.write(f"**Time:** {entry['timestamp']}")
                st.write(f"**Status:** {entry['status']}")
                if entry.get("response") and st.button("🔍 Load Result", key=f"load_hist_{entry['id']}"):
                    st.session_state.current_response = entry["response"]
                    st.rerun()

with main_tab2:
    st.subheader("Database Schema")

    connection_key = "demo" if st.session_state.use_demo_database else st.session_state.db_url
    if connection_key != st.session_state.schema_connection_key:
        st.session_state.schema_connection_key = connection_key
        st.session_state.schema_data = None

    if not connection_key:
        st.info("Connect a database first.")
    else:
        if st.session_state.schema_data is None:
            with st.spinner("Loading schema..."):
                schema_result = call_api(
                    SCHEMA_ENDPOINT,
                    method="POST",
                    data={"db_url": st.session_state.db_url}
                    if st.session_state.db_url
                    else {},
                )
            if schema_result["success"]:
                st.session_state.schema_data = schema_result["data"]
            else:
                st.error(schema_result["error"])

        schema_data = st.session_state.schema_data
        if schema_data:
            st.write(f"**Total Tables:** {len(schema_data.get('tables', []))}")
            cols = st.columns(3)
            for idx, table in enumerate(schema_data.get("tables", [])):
                with cols[idx % 3]:
                    st.write(f"• {table}")

            st.subheader("Formatted Schema")
            st.code(schema_data.get("formatted_schema", ""), language="sql")

with main_tab3:
    st.subheader("🎯 Feedback Loop & Flywheel")
    st.markdown("""
    The feedback loop is the flywheel that makes this system better over time:
    - **Correct results** → Few-shot examples (improve future generation)
    - **Incorrect results** → Test cases (find and fix bugs)
    """)
    
    # Show stats
    stats_result = call_api(FEEDBACK_STATS_ENDPOINT)
    
    if stats_result["success"]:
        stats = stats_result["data"]
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Feedback", stats["total_feedback"])
        with col2:
            st.metric("✅ Correct", stats["correct_feedback"])
        with col3:
            st.metric("❌ Incorrect", stats["incorrect_feedback"])
        with col4:
            st.metric("Test Cases", stats["total_test_cases"])
        
        st.markdown("---")
        
        # Tabs for different feedback views
        feedback_tab1, feedback_tab2, feedback_tab3 = st.tabs(
            ["📊 Statistics", "🧪 Test Cases", "💡 Few-Shot Examples"]
        )
        
        with feedback_tab1:
            st.subheader("Feedback Summary")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Total Examples Generated:**")
                st.write(f"- Few-shot examples: {stats['total_few_shot_examples']}")
                st.write(f"- Test cases: {stats['total_test_cases']}")
                st.write(f"- Fixed test cases: {stats['fixed_test_cases']}")
            
            with col2:
                feedback_data = {
                    "Correct": stats["correct_feedback"],
                    "Incorrect": stats["incorrect_feedback"]
                }
                st.bar_chart(feedback_data)
        
        with feedback_tab2:
            st.subheader("🧪 Test Cases (Incorrect Results)")
            st.markdown("These are queries marked as incorrect by users. They need to be fixed and added to the test suite.")
            
            test_cases_result = call_api(FEEDBACK_TEST_CASES_ENDPOINT)
            
            if test_cases_result["success"]:
                test_data = test_cases_result["data"]
                
                if test_data["test_cases"]:
                    for tc in test_data["test_cases"]:
                        with st.expander(f"❌ {tc['question'][:60]}..."):
                            st.write(f"**Test ID:** {tc['test_id']}")
                            st.write(f"**Created:** {tc['created_at']}")
                            st.write(f"**Error Reason:** {tc['error_reason']}")
                            st.code(tc["generated_sql"], language="sql")
                else:
                    st.info("No test cases yet! Keep using the system and marking incorrect results.")
            else:
                st.error(test_cases_result["error"])
        
        with feedback_tab3:
            st.subheader("💡 Few-Shot Examples (Correct Results)")
            st.markdown("These are queries marked as correct by users. They improve future generation through in-context learning.")
            
            examples_result = call_api(FEEDBACK_EXAMPLES_ENDPOINT, method="GET")
            
            if examples_result["success"]:
                examples_data = examples_result["data"]
                
                if examples_data["examples"]:
                    for ex in examples_data["examples"]:
                        with st.expander(f"✅ {ex['question'][:60]}..."):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write(f"**Category:** {ex['category']}")
                                st.write(f"**Confidence:** {ex['confidence']:.2f}")
                            with col2:
                                st.write(f"**Used:** {ex['usage_count']} times")
                            st.code(ex["sql"], language="sql")
                else:
                    st.info("No few-shot examples yet! Mark correct results to build the example library.")
            else:
                st.error(examples_result["error"])
    else:
        st.error(stats_result["error"])

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #888; font-size: 12px;">
    <p>Text-to-SQL Pipeline | Powered by LangChain + Groq | Database: PostgreSQL</p>
</div>
""", unsafe_allow_html=True)
