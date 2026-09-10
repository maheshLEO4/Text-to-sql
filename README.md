# Text-to-SQL Interface

Convert natural-language questions into safe, schema-aware SQL queries. The application combines FastAPI, Streamlit, PostgreSQL, Groq, and layered validation to generate, execute, and assess read-only database queries.

## Highlights

- Schema discovery and focused table selection
- SQL generation with Groq and few-shot feedback examples
- Read-only SQL guardrails, statement timeouts, and query-result sanity checks
- Backtranslation and multi-query consensus confidence signals
- FastAPI API, Streamlit interface, and feedback loop

## Architecture

```text
Streamlit UI --> FastAPI --> Text-to-SQL pipeline --> PostgreSQL
                    |              |
                    |              +--> Groq
                    +--> feedback store
```

## Run locally

Prerequisites: Python 3.11+, PostgreSQL, and a Groq API key.

1. Create the environment file and replace its placeholders:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Install dependencies and start the API:

   ```bash
   pip install -r requirements.txt
   uvicorn api.main:app --reload --port 8000
   ```

3. In a separate terminal, start the UI:

   ```bash
   streamlit run frontend/app.py
   ```

The API is available at `http://localhost:8000` and the UI at `http://localhost:8501`.

## Run with Docker Compose

Docker Compose starts PostgreSQL, the API, and the frontend together.

```powershell
Copy-Item .env.example .env
# Edit .env: set GROQ_API_KEY and replace POSTGRES_PASSWORD.
docker compose up --build
```

The frontend calls the API through Docker's internal `api` hostname; no local URL edits are needed. For a public deployment, set `ALLOWED_ORIGINS` in `.env` to the public frontend URL rather than leaving the local default.

## Tests

```bash
python -m unittest discover tests
```

GitHub Actions runs this test suite for pushes and pull requests to `main`.

## Deployment and GitHub checklist

1. Never commit `.env`; use `.env.example` as the template.
2. Change `POSTGRES_PASSWORD` and set a valid `GROQ_API_KEY` in the deployment environment.
3. Configure `ALLOWED_ORIGINS` to only the deployed frontend origin(s).
4. Confirm the containers start and `http://localhost:8000/health` returns `{"status":"ok"}`.
5. Push the repository:

   ```bash
   git add .
   git commit -m "Prepare application for deployment"
   git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
   git push -u origin main
   ```

## Project layout

- `api/` — FastAPI application
- `frontend/` — Streamlit interface
- `pipeline/` — end-to-end query orchestration and feedback persistence
- `ingestion/`, `generation/`, `safety/`, `verification/` — pipeline stages
- `tests/` — automated tests
- `docs/` — walkthroughs and design notes
