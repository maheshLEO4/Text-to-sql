import os
import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load environment settings (models, API keys)
load_dotenv(override=True)

from pipeline.pipeline_core import run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parent
SPIDER_DIR = PROJECT_ROOT / "spider_data" / "spider_data"
DEV_JSON = SPIDER_DIR / "dev.json"
TABLES_JSON = SPIDER_DIR / "tables.json"
DB_DIR = SPIDER_DIR / "database"

def normalize_sql(sql: str) -> str:
    """Basic SQL normalization for String Exact Match comparison."""
    if not sql:
        return ""
    # Lowercase, remove trailing semicolons and extra whitespace
    sql = sql.lower().strip().rstrip(";")
    return " ".join(sql.split())

def execute_sqlite_query(db_path: Path, sql: str) -> tuple[bool, list, str]:
    """Execute a query against a local Spider SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        results = cursor.fetchall()
        conn.close()
        return True, results, ""
    except Exception as e:
        return False, [], str(e)

def run_spider_evaluation(limit: int = None):
    """Run pipeline against Spider validation split and calculate key metrics."""
    if not DEV_JSON.exists():
        print(f"❌ Error: Could not find {DEV_JSON}. Please download the Spider dataset.")
        return
    if not TABLES_JSON.exists():
        print(f"❌ Error: Could not find {TABLES_JSON}. Please download the Spider dataset.")
        return
    if not DB_DIR.exists():
        print(
            f"❌ Error: Could not find {DB_DIR}. "
            "Download the Spider database directory before running evaluation."
        )
        return
    if not any(DB_DIR.glob("*/*.sqlite")):
        print(
            f"❌ Error: No SQLite databases found under {DB_DIR}. "
            "Extract the Spider database files before running evaluation."
        )
        return

    with open(DEV_JSON, "r") as f:
        test_cases = json.load(f)

    if limit:
        test_cases = test_cases[:limit]

    print(f"\n🚀 Starting Spider Evaluation on {len(test_cases)} query pairs...\n" + "="*70)

    exact_match_count = 0
    execution_match_count = 0
    successful_executions = 0
    total_evals = len(test_cases)

    results_log = []

    for idx, item in enumerate(test_cases, start=1):
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["query"]
        
        db_path = DB_DIR / db_id / f"{db_id}.sqlite"
        db_url = f"sqlite:///{db_path.resolve()}"

        print(f"\n[{idx}/{total_evals}] DB: {db_id} | Question: {question}")

        start_time = time.time()
        
        # 1. Run through your main Text-to-SQL Pipeline
        try:
            pipeline_res = run_pipeline(
                user_question=question,
                db_url=db_url
            )
            generated_sql = pipeline_res.generated_sql or ""
            p_status = pipeline_res.status
        except Exception as e:
            print(f"   ⚠️ Pipeline Exception: {e}")
            generated_sql = ""
            p_status = "ERROR"

        exec_time = time.time() - start_time

        # 2. Metric 1: Exact String Match (Normalized)
        norm_gold = normalize_sql(gold_sql)
        norm_gen = normalize_sql(generated_sql)
        is_exact_match = (norm_gold == norm_gen)
        if is_exact_match:
            exact_match_count += 1

        # 3. Metric 2: Execution Match (Compare returned dataset output)
        gold_ok, gold_data, _ = execute_sqlite_query(db_path, gold_sql)
        gen_ok, gen_data, gen_err = execute_sqlite_query(db_path, generated_sql)

        is_exec_match = False
        if gen_ok:
            successful_executions += 1
            # Check if execution result matches gold execution result regardless of order
            if set(map(str, gold_data)) == set(map(str, gen_data)):
                is_exec_match = True
                execution_match_count += 1

        print(f"   Gold SQL : {gold_sql}")
        print(f"   Gen SQL  : {generated_sql}")
        print(f"   Exact Match: {'✅' if is_exact_match else '❌'}")
        print(f"   Exec Match : {'✅' if is_exec_match else '❌'} (Exec OK: {gen_ok})")

        results_log.append({
            "test_id": idx,
            "db_id": db_id,
            "question": question,
            "gold_sql": gold_sql,
            "generated_sql": generated_sql,
            "status": p_status,
            "exact_match": is_exact_match,
            "execution_match": is_exec_match,
            "execution_success": gen_ok,
            "execution_error": gen_err if not gen_ok else None,
            "latency_seconds": round(exec_time, 2)
        })

        time.sleep(1.0)

    # Output Summary Metrics
    print("\n" + "="*70)
    print("📊 SPIDER EVALUATION SUMMARY")
    print("="*70)
    print(f"Total Evaluated Items : {total_evals}")
    print(f"Syntax/Exec Success   : {successful_executions}/{total_evals} ({successful_executions/total_evals*100:.1f}%)")
    print(f"Exact String Match    : {exact_match_count}/{total_evals} ({exact_match_count/total_evals*100:.1f}%)")
    print(f"Execution Accuracy    : {execution_match_count}/{total_evals} ({execution_match_count/total_evals*100:.1f}%)")
    print("="*70)

    # Save details to disk
    os.makedirs("data/eval_results", exist_ok=True)
    out_file = Path("data/eval_results/spider_results.json")
    with open(out_file, "w") as f:
        json.dump(results_log, f, indent=2)
    print(f"Detailed log saved to: {out_file}")

if __name__ == "__main__":
    # Test first 10 queries, or remove limit argument for full dev set
    run_spider_evaluation(limit=10)