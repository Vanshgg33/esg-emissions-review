# Tradeoffs — Things Deliberately Not Built

## 1. Authentication and authorisation

**What I didn't build:** User accounts, login, JWT/session auth, role-based access control (e.g., read-only vs. approver).

**Why I skipped it:** Adding auth doubles the backend surface area (login, refresh tokens, password reset, permission checks on every view) and adds a React auth context that touches every page. For a four-day prototype where the evaluators want to see data model quality and ingestion logic, spending time on boilerplate auth would be a poor use of effort.

The tenant selector in the UI simulates multi-tenancy without requiring login. A real deployment would add Django REST Framework's token auth or OAuth2 (via `django-allauth` + `drf-simplejwt`) in a day.

**What breaks without it:** Any user can see any tenant's data (though the API does filter by `tenant_id`). No accountability for who actually approved what beyond the `actor` string passed in the request body — which is currently a hardcoded email in the frontend.

**What I'd need to build it:** `AUTH_USER_MODEL`, `drf-simplejwt` for JWT, a permissions decorator on each view (`IsAuthenticated` + a tenant-membership check), and a login page in React.

---

## 2. Asynchronous ingestion via a task queue

**What I didn't build:** Celery + Redis (or similar) for background processing of uploads.

**Why I skipped it:** For prototype-scale files (hundreds to low thousands of rows), synchronous processing in the request-response cycle takes under a second and is easier to reason about. Adding Celery requires a broker (Redis), a worker process, and result polling on the frontend — that's three additional components to deploy and debug.

**What breaks without it:** A file with 100,000 rows (realistic for a full-year SAP dump) will time out on a 30-second Gunicorn worker. The request will fail mid-parse and leave the ingestion in PROCESSING state. The existing code structure makes this easy to fix — the processor functions are already extracted and could be called from a Celery task with one additional file.

**What I'd need to build it:** `celery[redis]`, a `@shared_task` wrapping each `_process_*` function, a `polling` endpoint on the ingestion, and a progress indicator in the UI.

---

## 3. Automatic anomaly detection across the dataset

**What I didn't build:** Statistical outlier detection — identifying records that are unusually high or low relative to historical baselines or peer records (e.g., this facility's electricity jumped 40% vs. last month).

**Why I skipped it:** The per-row quality flags (zero quantity, future date, very high CO2e) are implemented. Cross-record statistical analysis requires enough historical data to be meaningful and a deliberate choice of methodology — z-score vs. IQR, how to handle seasonal variation, whether to compare across facilities of different sizes. Getting this wrong produces noisy false positives that erode analyst trust faster than they add value.

**What I'd build instead:** A `POST /api/records/analyze/` endpoint that, given a tenant and date range, computes z-scores by category and period and updates `is_suspicious` accordingly. This would run after ingestion completes, using the full dataset rather than per-row heuristics.
