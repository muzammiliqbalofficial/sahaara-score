# Sahaara Score

**Alternative credit scoring for financially invisible Pakistanis.**

Most Pakistanis have no formal banking record, which locks them out of scholarships, micro-grants, and financial aid. Sahaara Score assesses eligibility using real-world signals that households already generate — utility bills, academic records, and income declarations — instead of bank statements.

Every score is **explainable**, because the output will be used by human reviewers awarding limited funds.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      FastAPI App                          │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Routers (API endpoints)                            │  │
│  │  /api/v1/applicants/*   /api/v1/assessments/*       │  │
│  └────────────────────┬────────────────────────────────┘  │
│                       │                                    │
│  ┌────────────────────▼────────────────────────────────┐  │
│  │  Services (business logic)                          │  │
│  │  scoring_service.py   feature_engineering.py        │  │
│  │  explainability.py                                   │  │
│  └────────────────────┬────────────────────────────────┘  │
│                       │                                    │
│  ┌────────────────────▼────────────────────────────────┐  │
│  │  Repositories (data access)                         │  │
│  │  applicant_repo.py    assessment_repo.py             │  │
│  └────────────────────┬────────────────────────────────┘  │
│                       │                                    │
│  ┌────────────────────▼────────────────────────────────┐  │
│  │  Models (SQLAlchemy ORM)    Schemas (Pydantic)      │  │
│  └────────────────────┬────────────────────────────────┘  │
│                       │                                    │
│                  PostgreSQL                                │
└──────────────────────────────────────────────────────────┘
```

### Project Structure

```
sahaara-score/
├── app/
│   ├── main.py                    # FastAPI application entry point
│   ├── config.py                  # Pydantic settings (env-driven)
│   ├── database.py                # SQLAlchemy engine + session
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── applicant.py
│   │   ├── utility_record.py
│   │   ├── academic_record.py
│   │   ├── income_signal.py
│   │   ├── assessment.py
│   │   └── reviewer_decision.py
│   ├── schemas/                   # Pydantic request/response validation
│   │   ├── applicant.py
│   │   ├── records.py
│   │   ├── assessment.py
│   │   └── review.py              # Reviewer dashboard schemas
│   ├── repositories/              # Data access layer
│   │   ├── applicant_repo.py
│   │   └── assessment_repo.py
│   ├── services/                  # Business logic layer
│   │   ├── feature_engineering.py # Raw data → numerical features
│   │   ├── scoring_service.py     # Features → 0-100 score + band
│   │   └── explainability.py      # Score → plain-language explanations
│   ├── routers/                   # API endpoint definitions
│   │   ├── applicants.py
│   │   ├── assessments.py
│   │   └── review.py              # Reviewer dashboard endpoints
│   └── utils/
│       └── enums.py               # Domain enumerations
├── frontend/                      # React reviewer interface
│   ├── src/
│   │   ├── api/                   # Types, fetch client, TanStack Query hooks
│   │   ├── components/            # Layout, ConfidenceBadge
│   │   ├── screens/               # ApplicantList, ApplicantDetail, SummaryView
│   │   ├── App.tsx                # Router configuration
│   │   └── main.tsx               # Entry point (React + QueryClient)
│   ├── index.html
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   ├── vercel.json                # SPA routing for Vercel deployment
│   └── package.json
├── alembic/                       # Database migrations
├── training/                      # Model training pipeline
│   ├── __init__.py
│   ├── dataset.py                 # Dataset builder (reuses feature engineering)
│   ├── train.py                   # LightGBM + isotonic calibration training
│   └── __main__.py                # Entry point: python -m training
├── scripts/
│   ├── seed.py                    # Synthetic data generator + label generation
│   ├── batch_score.py             # Batch-score all unscored applicants
│   ├── compare.py                 # Model vs rule-based comparison
│   └── diagnose.py                # Model diagnostic (MI, noise, scaling)
├── tests/                         # pytest test suite
│   ├── conftest.py
│   ├── test_feature_engineering.py
│   ├── test_scoring.py
│   ├── test_models.py
│   └── test_model_path.py         # Dual-path integration tests
├── models_cache/                  # Trained model artifacts
├── Dockerfile                     # Multi-stage production build (Cloud Run)
├── .dockerignore
├── docker-compose.yml             # Optional local Postgres alternative
├── requirements-prod.txt          # Production-only dependencies
├── requirements.txt               # Full dependencies (incl. testing)
├── pyproject.toml
└── .env.example
```

---

## Data Model

### Tables

| Table | Purpose | Key Nullable Fields |
|-------|---------|-------------------|
| `applicants` | Central entity every record hangs off | `identity_reference`, `household_size`, `city`, `district`, `dependants` |
| `utility_records` | Monthly electricity/gas/water bills | `amount_billed`, `amount_paid`, `days_late` |
| `academic_records` | Qualification results | `result_value`, `result_scale`, `year` |
| `income_signals` | Declared income sources | `declared_monthly_amount`, `evidence_type`, `confidence_flag` |
| `assessments` | Scoring output (score, band, explanations) | `feature_contributions` (JSONB) |
| `reviewer_decisions` | Human reviewer verdicts | `reviewer`, `rationale` |

### Nullable-First Design

**Every non-PK, non-FK field is nullable.** This is a deliberate architectural choice, not an oversight:

- A rural applicant may only know their tehsil, not their district.
- A student may have utility bills in their parent's name but no income record.
- A freelancer may have academic transcripts but no utility bills.

The scoring engine handles missing data explicitly — `None` is structurally different from a low value.

---

## Scoring Logic

### Feature Engineering

Raw records are transformed into 8 numerical features (all normalised to 0-1):

| Feature | Source | What it measures |
|---------|--------|-----------------|
| `payment_on_time_ratio` | Utility records | Fraction of bills paid on time (days_late == 0) |
| `longest_on_time_streak` | Utility records | Longest consecutive run of on-time payments (normalised: 12 months = 1.0) |
| `mean_days_late` | Utility records | Average lateness, inverted (0 days late = 1.0) |
| `payment_consistency` | Utility records | Coefficient of variation of billed amounts, normalised via exponential decay |
| `academic_signal` | Academic records | Best normalised result, weighted by qualification level and recency |
| `household_burden` | Applicant + Income + Utility | Composite of dependants-per-earner and utility-spend-to-income ratio |
| `income_confidence` | Income signals | Evidence-weighted confidence (verified > documented > self-declared) |
| `total_income_normalised` | Income signals | Log-scale normalisation of total declared PKR income |

#### Academic Normalisation

Pakistani institutions use three different grading systems. We normalise them to a common 0-1 scale:

- **Percentage** (matric/intermediate boards): `value / 100`
- **GPA** (universities): `value / 4.0`
- **Division** (older institutions): `{First: 0.85, Second: 0.65, Third: 0.45}`

A recency weight is applied: results from the current year get 1.0, decaying by 0.05 per year (minimum 0.7).

### Scoring Paths

The system uses **two scoring paths** depending on data sufficiency:

#### 1. Model-Based Path (LightGBM + SHAP)

Used when:
- A trained model exists in `models_cache/`
- The applicant has ≥ `min_model_data_points` (default: 6) non-null features

The LightGBM model predicts a 0-1 score, which is scaled to 0-100. SHAP values decompose the prediction into per-feature contributions.

#### 2. Rule-Based Fallback

Used when the model isn't available or the applicant has too few features (thin file).

Weights are hand-tuned to reflect domain priorities:

| Feature | Weight | Rationale |
|---------|--------|-----------|
| `payment_on_time_ratio` | 0.30 | Strongest signal of financial discipline |
| `academic_signal` | 0.15 | Commitment to education / self-improvement |
| `longest_on_time_streak` | 0.10 | Consistency over time |
| `mean_days_late` | 0.10 | Punctuality indicator |
| `payment_consistency` | 0.10 | Stable household |
| `household_burden` | 0.10 | Financial pressure indicator |
| `income_confidence` | 0.08 | Data credibility |
| `total_income_normalised` | 0.07 | Absolute income level |

**Critical design choice:** when a feature is `None`, its weight is *excluded from the denominator*. This means an applicant with only utility data isn't penalised for missing academic or income data — the available features are scored at full weight.

### Score Bands

| Score | Band | Interpretation |
|-------|------|---------------|
| 60-100 | Strong | Clear eligibility signal |
| 35-59 | Moderate | Eligible with caveats; reviewer should weigh context |
| 0-34 | Low | Weak signal; may need additional verification |

### Confidence Levels

| Level | Criteria |
|-------|----------|
| High | 3 signal categories present AND 6+ months of utility data |
| Medium | 2 categories OR 3+ months of data |
| Low | 1 category and <3 months — score is indicative but not definitive |

### Explainability

Every assessment includes **feature-level explanations** in plain language:

```json
{
  "feature": "payment_on_time_ratio",
  "label": "Payment Reliability",
  "contribution": 12.5,
  "direction": "positive",
  "explanation": "The applicant pays bills on time 90% of the time, showing strong financial discipline."
}
```

Missing features are explicitly listed with neutral explanations, so reviewers can see exactly what data gaps exist.

The `is_rule_based` flag on every assessment makes it **explicit** whether the ML model or the rule-based fallback produced the score. No hidden fallbacks.

#### Hard Gate: Zero-Feature Protection

An applicant below the minimum feature threshold (default: 6 of 8 features non-null) **never reaches the model**. A hard gate in `_score_model_based()` raises `RuntimeError` if a thin-file applicant somehow bypasses the routing logic. The model would output ~56.7 for an empty applicant — a fabricated number built on nothing. Missing data must never be read as ordinary data.

#### Data Sufficiency in Every Response

A score of 60 built on eight signals is not the same claim as a score of 60 built on one signal. Every assessment now returns:

- `signal_categories_count` — how many distinct signal categories (utility, academic, income) backed this score
- `non_null_feature_count` — how many of the 8 engineered features had actual values
- `confidence_level` — derived from category count and months of data
- `categories_present` — which categories were available
- `months_of_data` — how many months of utility history exist

These are first-class database columns, not side-channel metadata.

---

## Model Evaluation: Honest Findings

This section documents what was measured, what the numbers were, and what conclusion was drawn. This is the part most projects hide.

### What We Measured

We trained a LightGBM regressor on 500 synthetic applicants with independently generated approval labels (deliberately different weights from the rule-based scorer, plus realistic noise: 8% random flip, 5% contrarian cases).

### Results (v1.1.0 with isotonic calibration)

| Metric | Before calibration (v1.0) | After calibration (v1.1) |
|--------|--------------------------|--------------------------|
| ROC AUC | 0.5857 | 0.5824 |
| Accuracy | 0.58 | 0.57 |
| Precision | 0.56 | 0.60 |
| Recall | 0.90 | 0.75 |
| ECE (calibration) | 0.0663 | 0.0510 |

### Diagnostic Investigations

**1. Mutual Information Analysis — Is the signal in the data?**

Average MI = 0.0118. Features carry weak but non-trivial signal. The strongest features are `longest_on_time_streak` (MI=0.027), `payment_consistency` (MI=0.025), and `household_burden` (MI=0.020). Two features (`mean_days_late`, `academic_signal`) have MI=0.000 — they carry no measurable information about the label.

**2. Sample Size Scaling — Is 500 records too few?**

| Records | ROC AUC |
|---------|--------|
| 500 | 0.5986 |
| 2,000 | 0.5639 |
| 5,000 | 0.5822 |

AUC does NOT scale with data volume. The ceiling is not sample size.

**3. Label Noise — Did we over-noise the labels?**

| Noise level | ROC AUC |
|-------------|--------|
| 8% flip + 5% contrarian (current) | 0.5986 |
| 2% flip + 1% contrarian (low) | 0.6701 |
| 0% (zero noise) | 0.6715 |

Noise has moderate impact (delta AUC = 0.073). Even with zero noise, the model only reaches 0.67 — the signal itself is weak.

**4. Class Weighting + Calibration**

| Configuration | ROC AUC | ECE |
|---------------|---------|-----|
| Baseline (unweighted, uncalibrated) | 0.5986 | 0.052 |
| Class-weighted | 0.5978 | 0.066 |
| Class-weighted + calibrated | 0.6536 | 0.000 |
| Calibrated only | 0.6567 | 0.000 |

Isotonic calibration gives the largest improvement. Class weighting provides negligible benefit.

**5. Rule-Based Baseline Comparison**

| Path | ROC AUC |
|------|--------|
| Calibrated model (v1.1) | 0.58 |
| Rule-based scorer | 0.57 |

The model marginally outperforms the rule-based baseline, but both are barely above random (0.50). Neither path provides strong predictive power on synthetic data.

### Honest Conclusion

**The model does not meaningfully beat the rule-based baseline.** Both paths produce weak results because the underlying features carry very little mutual information with the approval labels. The synthetic data is intentionally noisy and realistic — which means the signal-to-noise ratio is low.

The rule-based path remains the primary scoring mechanism. The model path serves as a supplementary signal. This is not a failure — it is the expected outcome when building a scoring system before real-world outcome data exists. The model will improve once trained on actual reviewer decisions rather than synthetic labels.

The `scripts/diagnose.py` script is included so anyone can reproduce these findings.

---

## Getting Started

### Prerequisites

- Python 3.11+
- A [Neon](https://neon.tech) Postgres project (free tier works fine)

### Setup

```bash
# 1. Clone and enter the project
cd saahara-score

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env from the example and paste your Neon connection string.
#    Change the URL prefix from postgresql:// to postgresql+psycopg://
#    and make sure sslmode=require is present.
cp .env.example .env
# Edit .env → set DATABASE_URL to your Neon URL

# 5. Run migrations
alembic upgrade head

# 6. Seed synthetic data (~500 applicants)
python -m scripts.seed

# 7. Batch-score all seeded applicants
python -m scripts.batch_score

# 8. Run the API server
uvicorn app.main:app --reload --port 8000

# 9. In a separate terminal, start the reviewer interface
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

> **Connection string note:** Neon provides URLs starting with `postgresql://`.
> SQLAlchemy needs the driver prefix, so change it to `postgresql+psycopg://`.
> Always keep `?sslmode=require` — Neon rejects non-SSL connections.

### API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/applicants/` | Register a new applicant |
| GET | `/api/v1/applicants/{id}` | Get applicant with all records |
| POST | `/api/v1/applicants/{id}/utility` | Add a utility bill record |
| POST | `/api/v1/applicants/{id}/academic` | Add an academic record |
| POST | `/api/v1/applicants/{id}/income` | Add an income signal |
| POST | `/api/v1/assessments/{applicant_id}/score` | **Run scoring** |
| GET | `/api/v1/assessments/{id}` | Get assessment with explanations |

### Running Tests

```bash
# Run all tests (no database required)
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_feature_engineering.py
```

---

## Reviewer Interface

A React-based web interface lets reviewers interact with scored applicants directly, replacing raw API calls with a usable tool.

### Stack

- **React 18** with **Vite** and **TypeScript**
- **Tailwind CSS** for styling
- **TanStack Query** for data fetching and caching
- **React Router** for navigation

### Screens

**Applicant List** — Sortable, filterable table of all scored applicants. Columns: score (always paired with confidence badge), band, ID/type, city, review status, created date. Filters for band, confidence level, and review status. Free-text search by city, district, or CNIC.

**Applicant Detail** — The core screen. Shows score and band prominently alongside the confidence level and which signal categories were present. Below that, the top contributing factors rendered as a bar chart with direction, magnitude, and plain-language explanation. States explicitly which scoring path produced the result (model or rule-based). Shows the underlying records: utility history, academic records, income signals. A reviewer can trace any number back to its evidence.

**Decision Panel** — Embedded in the detail screen. Lets the reviewer record an approval or denial with a written rationale, saved to the `reviewer_decisions` table. Shows any previous decisions on the applicant.

**Summary View** — Score distribution in 10-point bins, band breakdown, confidence breakdown, data completeness, and decision counts.

### Design Principles

- **Never display a score without its confidence attached.** Every score in the interface — list table, detail header, summary — is always shown alongside its confidence badge.
- **Colour carries meaning, not decoration.** Confidence uses green (high), amber (medium), red (low). Bands use the same semantic palette. No colour is used purely for aesthetics.
- **Calm and legible.** No gauge widgets, no gratuitous animation, no dashboard theatrics. This is a tool for consequential decisions about people with limited means.

### Frontend Setup

```bash
# Prerequisites: Node.js 18+ and the backend running on port 8000.

# 1. Enter the frontend directory
cd frontend

# 2. Install dependencies
npm install

# 3. Start the dev server (proxies /api/* to localhost:8000)
npm run dev
```

The frontend runs on **http://localhost:5173** and proxies all `/api/*` requests to the backend at `http://localhost:8000`. No separate CORS configuration is needed in development because Vite handles the proxy.

To batch-score all seeded applicants before opening the interface:

```bash
# From the project root (with venv active)
python -m scripts.batch_score
```

### Reviewer API Endpoints

The frontend talks to these endpoints, added alongside the existing API:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/review/applicants` | List scored applicants (filter, sort, paginate) |
| GET | `/api/v1/review/applicants/{id}` | Full detail with records + decisions |
| POST | `/api/v1/review/assessments/{id}/decisions` | Submit reviewer decision |
| GET | `/api/v1/review/summary` | Aggregate statistics |

---

## Design Decisions

### Why nullable-first?

In the Pakistani context, a complete data profile is the exception, not the norm. A day labourer in Jacobabad may have 12 months of electricity bills but no academic record and no provable income. A matric student in rural Punjab may have academic results and a parent's utility bills but nothing in her own name. The system must score all of them fairly.

### Why two scoring paths?

An ML model trained on historical data can capture non-linear interactions between features — but only when there are enough features to work with. For thin-file applicants, a transparent weighted-average is more honest than a model guessing at patterns it can't see. The rule-based path is never hidden: every assessment carries `is_rule_based: true/false`.

### Why store raw academic values?

Storing the raw `result_value` alongside its `result_scale` means we never lose information. When we add a new scale (e.g. letter grades) or adjust the normalisation mapping, existing data doesn't need migration. The feature engineering layer handles all interpretation.

### Why confidence levels alongside scores?

A score of 45 from a thin file (1 category, 2 months of data) means something very different from a score of 45 from a full file (3 categories, 12 months). Without the confidence level, a reviewer might treat them identically. The confidence level forces the reviewer to calibrate their trust in the number.

---

## Deployment

### Backend — Google Cloud Run

#### Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`) installed and authenticated
- A GCP project with Cloud Run API enabled
- Docker installed locally (for building)
- A Neon database connection string

#### Build and deploy

```bash
# Set your project and region (adjust to your preferences)
gcloud config set project YOUR_PROJECT_ID
REGION=asia-southeast1   # or us-central1, europe-west1, etc.

# Build the container image and push to Artifact Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/sahaara-api

# Deploy to Cloud Run
gcloud run deploy sahaara-api \
  --image gcr.io/YOUR_PROJECT_ID/sahaara-api \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 120 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "DATABASE_URL=postgresql+psycopg://user:pass@host/db?sslmode=require" \
  --set-env-vars "APP_ENV=production" \
  --set-env-vars "APP_DEBUG=false" \
  --set-env-vars "APP_SECRET_KEY=$(openssl rand -hex 32)" \
  --set-env-vars "CORS_ORIGINS=[\"https://your-frontend.vercel.app\"]" \
  --set-env-vars "SQL_ECHO=false"
```

Replace `YOUR_PROJECT_ID` and the database URL with your actual values. After deployment, `gcloud` prints the service URL (e.g. `https://sahaara-api-xxxxx.asia-southeast1.run.app`). Save this — you need it for the frontend.

#### Updating environment variables

```bash
gcloud run services update sahaara-api \
  --region $REGION \
  --update-env-vars "CORS_ORIGINS=[\"https://new-frontend.vercel.app\"]"
```

#### Environment variables

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DATABASE_URL` | **Yes** | — | Neon connection string with `postgresql+psycopg://` prefix and `sslmode=require` |
| `APP_ENV` | No | `development` | Set to `production` |
| `APP_DEBUG` | No | `true` | Set to `false` in production (disables /docs and /redoc) |
| `APP_SECRET_KEY` | No | `change-me-in-production` | Generate with `openssl rand -hex 32` |
| `CORS_ORIGINS` | No | localhost origins | JSON array: `["https://app.vercel.app"]` |
| `SQL_ECHO` | No | `false` | Log all SQL — dev only |
| `MODEL_VERSION` | No | `0.1.0` | Stamped on assessments |
| `MIN_MODEL_DATA_POINTS` | No | `6` | Min features before model path activates |

#### Health check

Cloud Run uses `/health` for readiness probes. The endpoint executes `SELECT 1` against the database, so it confirms actual connectivity — not just that the process is alive.

```
GET /health
→ {"status": "healthy", "database": "healthy", "version": "1.1.0-...", "env": "production"}
```

#### Seeding the production database

After first deploy, the database has no data. From your local machine (with `DATABASE_URL` pointing to production Neon):

```bash
# Run migrations against the production database
DATABASE_URL="postgresql+psycopg://..." python -m alembic upgrade head

# Seed 500 synthetic applicants
DATABASE_URL="postgresql+psycopg://..." python -m scripts.seed

# Batch-score them all
DATABASE_URL="postgresql+psycopg://..." python -m scripts.batch_score
```

Or run the same commands inside a Cloud Run Job if you prefer not to expose the database URL locally.

---

### Frontend — Vercel

#### Prerequisites

- A [Vercel](https://vercel.com) account
- The backend deployed and its URL known

#### Deploy

1. Push the repo to GitHub.
2. Import the project in Vercel. Set the **Root Directory** to `frontend`.
3. Vercel auto-detects Vite. Build command: `npm run build`. Output: `dist`.
4. Add the environment variable:

| Variable | Value |
|----------|-------|
| `VITE_API_BASE_URL` | `https://sahaara-api-xxxxx.run.app/api/v1` |

5. Deploy. Vercel builds the static site and serves it from its CDN.

#### SPA routing

The `frontend/vercel.json` file rewrites all paths to `/index.html` so direct links to applicant detail pages work without a 404:

```json
{
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

#### Local development (unchanged)

The Vite dev proxy (`frontend/vite.config.ts`) still forwards `/api/*` to `localhost:8000` for local work. The `VITE_API_BASE_URL` variable is only needed for the production build — when unset, the client falls back to the relative `/api/v1` path that the proxy handles.

---

### Cold Start

Both Cloud Run (scale-to-zero) and Neon (idle connection suspension) suspend after inactivity. The first request after a quiet period pays a compounded cold start:

| Layer | Cold cost | Mitigation |
|-------|-----------|------------|
| Cloud Run container | 1–3 s | `--min-instances 1` ($30–50/month depending on region) |
| Neon database | 1–5 s | Neon paid plan "Keep alive" ($19/month), or a cron pinging `/health` every 4 min |
| Combined worst case | 5–8 s | Both mitigations together |

The `/health` endpoint is designed to be the ping target — it wakes both layers because it opens a real database connection.

**Options ranked by cost:**

1. **Free**: accept 5–8 s cold starts (fine for infrequent demos)
2. **~$0/month**: Use a free cron service (cron-job.org, GitHub Actions schedule) to `GET /health` every 4 minutes, keeping Cloud Run warm
3. **~$19/month**: Neon paid plan keeps the database alive, reducing cold to 1–3 s
4. **~$50/month**: `--min-instances 1` on Cloud Run + Neon keep-alive eliminates cold starts entirely

---

## Next Steps (Future Phases)

1. **Collect real outcome data** — The model is currently trained on synthetic labels. The single most impactful improvement is retraining on actual reviewer decisions as they accumulate through the interface.
2. **Data collection integration** — Mobile-first forms for field workers to capture utility bills and income signals.
3. **Appeals workflow** — Structured process for applicants to submit additional evidence and request re-scoring.
4. **Fairness auditing** — Statistical checks for bias across city, district, gender, and applicant type.

---

## Alternative: Local Postgres via Docker Compose

If you prefer not to use a hosted database, a `docker-compose.yml` is included
for running Postgres locally. This is optional and not the default path.

```bash
# Start local Postgres
docker compose up -d

# Use the local URL in your .env:
# DATABASE_URL=postgresql+psycopg://sahaara:sahaara_dev@localhost:5432/sahaara_score
```
