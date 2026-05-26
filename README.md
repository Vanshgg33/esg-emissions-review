# BreathESG — Emissions Data Ingestion & Review

Django REST + React prototype for ingesting fuel (SAP), electricity (utility portal), and corporate travel (Concur) data, normalising it to CO₂e, and surfacing a review dashboard for analyst sign-off before audit.

---

## Running Locally

### 1. Clone the repo

```bash
git clone <repo-url>
cd "Assesment BreathESG"
```

### 2. Backend (Django)

Run all of these from the `backend/` directory:

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Copy environment config (defaults work for local dev)
cp .env.example .env

# Apply database migrations
python manage.py migrate

# Seed demo tenant + ingest all three sample data files
python manage.py seed_data

# Start the Django dev server on port 8000
python manage.py runserver
```

Backend is now running at **http://localhost:8000**  
Admin panel: **http://localhost:8000/admin** (create a superuser with `python manage.py createsuperuser`)

### 3. Frontend (React)

Open a **new terminal** and run from the `frontend/` directory:

```bash
cd frontend

# Install Node dependencies
npm install

# Start the Vite dev server on port 5173 (proxies /api → localhost:8000)
npm run dev
```

Frontend is now running at **http://localhost:5173**

Open it in a browser. The tenant "CJP Corporation" is pre-selected with 72 seeded records across all three source types.

---

## What you'll see

| Page | What it does |
|---|---|
| **Dashboard** | Summary stats — total CO₂e, scope breakdown, recent ingestions |
| **Ingest Data** | Upload a source file (SAP .txt, utility .csv, travel .csv); shows parse warnings/errors |
| **Review** | Filterable table of all normalised records; approve / reject / flag individually or in bulk; click a row to see raw data, emission factor details, and audit trail |

Sample files to upload are in `backend/sample_data/`:
- `sap_fuel_mm60.txt` — SAP MM60 fuel consumption export (tab-delimited, German headers)
- `utility_portal.csv` — Utility portal electricity export (kWh per billing period per meter)
- `travel_concur.csv` — Concur expense report (flights, hotels, ground transport)

---

## Project layout

```
backend/
  apps/
    core/              Tenant model
    ingestion/
      models.py        DataIngestion, RawRecord, NormalizedRecord, AuditEvent
      parsers/
        sap.py         SAP MM60 flat file parser (German/English headers, unit normalisation)
        utility.py     Utility portal CSV parser (kWh/MWh, billing period handling)
        travel.py      Concur CSV parser + IATA haversine distance calculation
      views.py         REST API: upload, review, bulk-review, dashboard
  sample_data/         Realistic sample files for all three source types
  requirements.txt
  Procfile             For Render/Railway deployment
frontend/
  src/
    pages/
      Dashboard.tsx    Stats + scope breakdown + recent ingestions
      Ingest.tsx       File upload form + ingestion history with parse log
      Review.tsx       Filterable record table + detail drawer + audit trail
MODEL.md               Data model and design rationale (start here for evaluation)
DECISIONS.md           Every ambiguity resolved — format choices, workflow decisions
TRADEOFFS.md           Three things deliberately not built and why
SOURCES.md             Research notes on SAP, utility, and travel data formats
render.yaml            One-click Render deployment config
```

---

## API Reference

All endpoints under `/api/`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/tenants/` | List tenants |
| `POST` | `/tenants/` | Create tenant |
| `POST` | `/ingestions/upload/` | Upload + parse a source file |
| `GET` | `/ingestions/?tenant_id=` | List ingestion runs |
| `GET` | `/records/?tenant_id=&scope=&review_status=&source_type=&suspicious=` | List normalised records (paginated) |
| `PATCH` | `/records/{id}/review/` | Update review status (APPROVED / REJECTED / FLAGGED) |
| `POST` | `/records/bulk-review/` | Bulk approve or reject |
| `GET` | `/records/{id}/audit/` | Audit trail for a record |
| `GET` | `/dashboard/?tenant_id=` | Summary stats |

---

## Deployment (Render)

The `render.yaml` at the root defines two services — a Python backend and a React static frontend — plus a managed PostgreSQL database.

1. Push this repo to GitHub (private is fine)
2. Go to [render.com](https://render.com) → New → Blueprint
3. Connect the repo — Render reads `render.yaml` and creates all three resources automatically
4. Set `VITE_API_URL` in the frontend service to your backend's Render URL
5. The `preDeployCommand` runs migrations and seeds demo data on first deploy

Environment variables needed on the backend service:

| Variable | Value |
|---|---|
| `SECRET_KEY` | Any long random string (Render can generate) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `*` |
| `DATABASE_URL` | Auto-set by Render from the PostgreSQL addon |
| `CORS_ALLOWED_ORIGINS` | Your frontend Render URL |

---

## Key design decisions

See [MODEL.md](MODEL.md), [DECISIONS.md](DECISIONS.md), [TRADEOFFS.md](TRADEOFFS.md), [SOURCES.md](SOURCES.md).
