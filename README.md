---
title: Intelli Credit
emoji: 💰
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# Intelli-Credit

AI-powered credit analysis platform that combines ML scoring, NLP document extraction, graph-based fraud detection, and LLM-driven research to produce comprehensive Credit Approval Memorandums (CAMs).

## Architecture

The platform runs a **5-stage pipeline** for each credit analysis:

| Stage | Module | Description |
|-------|--------|-------------|
| 1. Ingest | `src/ingestor/` | PDF/Excel parsing, BERT-NER entity extraction, FinBERT sentiment analysis, Delta Lake persistence |
| 2. Enrich | `src/agent/` | LangGraph research agent with parallel Tavily, eCourts, MCA21, RBI tools via Claude Haiku |
| 3. Score | `src/scorer/` | 35-feature vector, LightGBM+RF ensemble (60/40 VotingClassifier), GraphSAGE GNN fraud detection |
| 4. Synthesize | `src/agent/synthesizer.py` | Claude-driven narrative synthesis with divergence detection |
| 5. Report | `src/cam/` | Five Cs CAM generation, PDF rendering via ReportLab |

**Data flows** through a medallion architecture: Raw -> Bronze (parsed) -> Silver (normalised) -> Gold (features/scores).

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **Frontend:** React 18, TypeScript, Vite, TailwindCSS, Zustand, TanStack React Query
- **ML Models:** LightGBM, scikit-learn, PyTorch, PyTorch Geometric (GraphSAGE)
- **NLP:** HuggingFace Transformers (FinBERT, BERT-NER)
- **LLM:** Anthropic Claude Haiku via LangGraph
- **Storage:** Delta Lake with local JSONL fallback

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys (see [Environment Variables](#environment-variables))

### Backend

```bash
# Install dependencies
pip install -r requirements.txt

# Start the API server
python run_api.py                  # default: http://localhost:8000
python run_api.py --port 9000      # custom port
python run_api.py --reload         # dev mode with hot-reload
python run_api.py --workers 4      # multi-process production mode
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
npm run build        # production build
```

## API Endpoints

All API routes are prefixed with `/api/v1/`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health with per-component status (`ok` / `degraded` / `offline`) |
| GET | `/health/ready` | Readiness probe (Python version, model files, output dirs) |
| GET | `/api/v1/health` | Same as above (also mounted under API prefix) |

### Analysis

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/analysis/pipeline` | Yes | Submit async pipeline job. Form fields: `company_name` (required), `cin`, `pdf_file`. Returns 202 + `job_id`. |
| GET | `/api/v1/analysis/jobs/{job_id}` | Yes | Poll job status (`PENDING` / `RUNNING` / `COMPLETED` / `FAILED`) |

### Debug

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/analysis/debug/pipeline/{job_id}/trace` | Yes | Full pipeline trace: `stage_results`, `data_quality_report`, errors, logs |
| POST | `/api/v1/analysis/debug/sample-run` | Yes | Smoke test with bundled sample data |

### Authentication

All `/analysis/*` endpoints require the `X-API-Key` header. Default dev key: `dev-key-change-in-production`.

Set via environment variable `INTELLI_API_KEY`, or disable in development by setting `INTELLI_DISABLE_AUTH=true`.

## Environment Variables

All configuration is read from environment variables with the `INTELLI_` prefix. Defaults are production-safe.

### Pipeline Decision Thresholds

| Variable | Default | Description |
|----------|---------|-------------|
| `INTELLI_HARD_REJECT_BOUNCE_COUNT` | `5` | Max cheque bounces before auto-reject |
| `INTELLI_HARD_REJECT_DEFAULT_PROB` | `0.10` | PD threshold for hard rejection |
| `INTELLI_PRIME_PD_THRESHOLD` | `0.05` | PD ceiling for PRIME risk band |
| `INTELLI_PARTIAL_APPROVE_PD_THRESHOLD` | `0.10` | PD ceiling for partial approval |
| `INTELLI_PRIME_RATE` | `9.50` | Base lending rate (%) |
| `INTELLI_MCLR_SPREAD` | `0.75` | MCLR spread (%) |

### NLP & Scoring

| Variable | Default | Description |
|----------|---------|-------------|
| `INTELLI_AUDITOR_SENTIMENT_THRESHOLD` | `-0.3` | Auditor sentiment flag threshold |
| `INTELLI_PDF_MIN_TEXT_LENGTH` | `500` | Min extracted chars to consider PDF valid |
| `INTELLI_GNN_MIN_TRAINING_SAMPLES` | `5` | Min samples for GNN training |
| `INTELLI_SYNTH_DIVERGENCE_THRESHOLD` | `2.5` | Score-narrative divergence alert threshold |

### Safe Defaults (imputed when data missing)

| Variable | Default | Description |
|----------|---------|-------------|
| `INTELLI_SAFE_DEFAULT_GST_HEALTH` | `5.0` | Default GST health score |
| `INTELLI_SAFE_DEFAULT_NEWS_RISK` | `5.0` | Default news risk score |
| `INTELLI_SAFE_DEFAULT_RATIO` | `0.0` | Default financial ratio |

### Timeouts & LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `INTELLI_PIPELINE_JOB_TIMEOUT_SECONDS` | `900` | Max pipeline execution time |
| `INTELLI_RESEARCH_TOOL_TIMEOUT_SECONDS` | `30` | Per-tool timeout in research agent |
| `INTELLI_CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model identifier |
| `INTELLI_CLAUDE_MAX_TOKENS` | `1000` | Max tokens per Claude call |
| `INTELLI_CLAUDE_TIMEOUT_SECONDS` | `60` | Claude API call timeout |

### External API Keys

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `TAVILY_API_KEY` | For research | News search API key |
| `INTELLI_API_KEY` | No | Override default API key for auth |

## Project Structure

```
intelli_credit/
  run_api.py                  # Server launcher
  requirements.txt            # Python dependencies
  models/
    pipeline_models.py        # All typed dataclasses & enums (single source of truth)
    gnn_fraud_detector.pt     # Trained GNN model weights
  src/
    config.py                 # Central config (env-var backed thresholds)
    api/
      main.py                 # FastAPI app factory with lifespan
      config.py               # Pydantic Settings (API key, ports)
      dependencies.py         # Startup validation, auth, component health
      routers/
        health.py             # /health, /health/ready
        analysis.py           # /analysis/pipeline, /analysis/jobs, /debug
      services/
        pipeline_service.py   # 5-stage pipeline orchestrator
    ingestor/
      pdf_parser.py           # PDF text extraction (pdfplumber + OCR fallback)
      ner_extractor.py        # BERT-NER + FinBERT entity/sentiment extraction
      bank_analyzer.py        # Bank statement parsing & EWS flag detection
      delta_writer.py         # Append-only JSONL persistence (Delta fallback)
    agent/
      research_agent.py       # LangGraph StateGraph with parallel tools
      synthesizer.py          # Claude narrative synthesis
      tools/                  # Tavily, eCourts, MCA21, RBI tool implementations
    scorer/
      feature_builder.py      # 35-feature vector construction
      credit_scorer.py        # LightGBM+RF ensemble + SHAP explanations
    gst/
      gnn_detector.py         # GraphSAGE fraud detection
    cam/
      five_cs_writer.py       # Claude-generated Five Cs CAM sections
  frontend/
    src/
      api/
        client.ts             # Axios client (429 retry, auth headers)
        health.ts             # Health check API
      components/
        shared/
          HealthBanner.tsx     # System health banner (30s polling)
          DataQualityPanel.tsx # Pipeline stage timing & data quality display
      pages/
        Results.tsx            # Analysis results with quality overlay
      store/
        types.ts              # TypeScript interfaces (FullPipelineResult, etc.)
  data/
    raw/                      # Unprocessed input files
    bronze/                   # Parsed documents (per-company)
    silver/                   # Normalised features
    gold/                     # Aggregated feature sets & scores
  tests/                      # Test suites (see Testing section)
```

## Testing

All tests are standalone Python scripts (no pytest required). Run individually:

```bash
# Type/model tests (64 tests)
python tests/test_pipeline_models.py

# Credit scoring logic (30 tests)
python tests/test_credit_scorer.py

# NER extraction & sentiment (35 tests)
python tests/test_ner_extractor.py

# Health endpoints (18 tests)
python tests/test_health_router.py

# Analysis API endpoints (22 tests)
python tests/test_analysis_router.py

# Run all tests
python tests/test_pipeline_models.py && python tests/test_credit_scorer.py && python tests/test_ner_extractor.py && python tests/test_health_router.py && python tests/test_analysis_router.py
```

**Total: 169 tests** across 5 suites.

On Windows, set `$env:PYTHONIOENCODING="utf-8"` before running if you see Unicode encoding errors.

## Verification Checklist

| ID | Check | How to verify |
|----|-------|---------------|
| VERIFY-01 | Health endpoint returns component status | `GET /health` returns `{status, components}` |
| VERIFY-02 | Pipeline returns 202 + job_id | `POST /api/v1/analysis/pipeline` with `company_name` |
| VERIFY-03 | Job polling works | `GET /api/v1/analysis/jobs/{job_id}` returns status |
| VERIFY-04 | Auth rejection on missing key | `POST /analysis/pipeline` without `X-API-Key` returns 401 |
| VERIFY-05 | Debug trace available | `GET /debug/pipeline/{job_id}/trace` returns stage_results |
| VERIFY-06 | Risk band classifications | Score >= 7.0 = PRIME, >= 5.0 = LOW, >= 3.0 = MEDIUM, < 3.0 = HIGH |
| VERIFY-07 | Feature vector shape | `feature_builder.build_feature_vector()` returns 35-element dict |
| VERIFY-08 | All test suites pass | Run all 5 test scripts, expect 169/169 pass |

## Risk Band Classification

| Band | Score Range | Decision |
|------|-------------|----------|
| PRIME | >= 7.0 | Full approval at prime rate |
| LOW | >= 5.0 | Approval with standard terms |
| MEDIUM | >= 3.0 | Partial approval / enhanced monitoring |
| HIGH | < 3.0 | Reject or refer to committee |

## License

Private - IIT Hyderabad