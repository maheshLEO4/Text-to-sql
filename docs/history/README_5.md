# Day Summary and Fix Log

## Date
2026-08-17

## Overview
This document summarizes the work completed today on the Text-to-SQL project, including the model fix, feedback-loop repair, UI refresh fix, and persistence cleanup.

## What was fixed today

### 1. LLM model configuration was made environment-driven
We replaced hard-coded model names with environment-based loading from the `.env` file.

Key updates:
- [generation/llm_client.py](../generation/llm_client.py)
- [generation/sql_generator.py](../generation/sql_generator.py)
- [verification/hallucination_detector.py](../verification/hallucination_detector.py)
- [verification/multi_query_validator.py](../verification/multi_query_validator.py)

Important fixes:
- Removed invalid hard-coded model names such as `gpt-oss-120b` and `llama-3.3-70b-versatile`
- Standardized Groq initialization to use the configured `GROQ_MODEL`
- Added environment-safe fallback behavior
- Ensured `.env` values are loaded consistently with `load_dotenv(override=True)`

The project now reads from:
- [\.env](../.env)

with a configuration like:

```env
GROQ_API_KEY=...
GROQ_MODEL=llama-3.1-8b-instant
```

### 2. The feedback loop was repaired
The feedback flow was incomplete: feedback was being saved, but it was not being used to improve future prompt generation.

We fixed the connection between saved feedback and prompt generation by updating:
- [pipeline/feedback_store.py](../pipeline/feedback_store.py)
- [pipeline/pipeline_core.py](../pipeline/pipeline_core.py)
- [generation/prompt_constructor.py](../generation/prompt_constructor.py)

What was corrected:
- Correct feedback now becomes few-shot examples
- Those examples are loaded back into the prompt builder
- The LLM now receives saved sample examples during SQL generation

This creates the true flywheel:
- correct result -> few-shot example -> better future prompts
- incorrect result -> test case -> regression debugging

### 3. Feedback persistence was fixed
A major bug was caused by writing and reading feedback using a stale or non-project-relative path. This meant new entries were not always landing in the actual project data folder.

Fixes:
- Resolved the base path to the project root instead of the current working directory
- Ensured new feedback is written to the real project files under:
  - [data/feedback/feedback_log.json](../data/feedback/feedback_log.json)
  - [data/feedback/few_shot_examples.json](../data/feedback/few_shot_examples.json)
  - [data/feedback/test_cases.json](../data/feedback/test_cases.json)

### 4. UI refresh was fixed
The frontend analytics were not updating because the app was not rerunning after a feedback submission.

Updated:
- [frontend/app.py](../frontend/app.py)

Fix:
- After a successful feedback submission, the app now calls `st.rerun()` so the dashboard refreshes immediately.

### 5. Timeout issue mitigation
We also adjusted the frontend request timeout to avoid early client-side aborts during slow Groq/DB work.

Updated:
- [frontend/app.py](../frontend/app.py)

This raised the timeout from a short window to a more realistic value so generation and execution can finish.

## Important findings

### Root cause of broken feedback loop
The feedback system was only half implemented:
- it saved feedback into files
- but it never fed the saved examples back into generated prompts
- so the model could not actually learn from previous correct answers

### Root cause of stale UI stats
The analytics view read from the API, but the app never refreshed after feedback was posted, so the front-end displayed stale values.

### Root cause of missing JSON writes
The store used a relative path that could resolve differently depending on the startup location, causing writes to appear to fail or fall into the wrong place.

## Current project status
The project now has:
- environment-driven model configuration
- working feedback persistence
- prompt learning from saved examples
- live UI refresh after feedback
- real project-path persistence for JSON data

## Relevant files
- [api/main.py](../api/main.py)
- [pipeline/pipeline_core.py](../pipeline/pipeline_core.py)
- [pipeline/feedback_store.py](../pipeline/feedback_store.py)
- [generation/prompt_constructor.py](../generation/prompt_constructor.py)
- [generation/sql_generator.py](../generation/sql_generator.py)
- [frontend/app.py](../frontend/app.py)
- [docs/FEEDBACK_LOOP.md](FEEDBACK_LOOP.md)

## Next recommended step
Restart the running API and Streamlit app, then validate the end-to-end feedback flow:
1. run a query
2. mark it correct
3. check that the feedback count updates
4. confirm the saved example is used in the next prompt
