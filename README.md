# FlowCare

**Hospital waiting-time intelligence — a student project using synthetic data by default.**

FlowCare is a modular full-stack outpatient queue demo. It includes staff login with role checks, patient reference and token registration, a live queue, persistent queue-status events, an explainable wait-time baseline, an optional trained Random Forest, a repeatable event-based staffing simulator, analytics, bottleneck signals, and an Android APK build workflow.

> The demo is not a clinical tool. Predictions are estimates, bottleneck messages are signals rather than causal findings, and simulation/training outputs are synthetic. Do not enter real patient data in this demo.

## Project architecture (Phase 1)

```text
frontend/ React + TypeScript + Vite + Recharts + Capacitor Android
backend/  FastAPI modular monolith, SQLAlchemy, Alembic, SQLite/PostgreSQL
ml/       Synthetic event generator and chronological Random Forest evaluation
docs/     Database, API, privacy, and operating notes
```

The web client uses a same-origin `/api` Vite proxy in local development and `VITE_API_BASE_URL` for mobile/production builds. FastAPI owns authentication, role authorization, input validation, audit events, and queue state changes. SQLAlchemy maps a relational schema; migrations are versioned with Alembic. SQLite is the zero-setup local default; set `DATABASE_URL` to a PostgreSQL URL for deployment.

### Database entities

| Table | Purpose |
|---|---|
| `users` | Staff identity, role, password hash, active flag |
| `departments` | Department code, available staff, typical service time |
| `patients` | Random patient reference and optional demo display name |
| `queue_tickets` | Daily department token, visit type, state and historical timestamps |
| `queue_events` | Append-only queue status transition history and actor |
| `prediction_records` | Predicted duration, feature snapshot, model, timestamp and observed wait |
| `simulation_records` | Reproducible simulation parameters and result summary |
| `audit_logs` | Administrative and workflow actions |

Appointment scheduling, per-stage workflows, staff schedules/break calendars, alert acknowledgement storage, refresh tokens, PostgreSQL concurrency stress tests, and calibrated uncertainty intervals are intentionally future extensions, not represented as complete features.

### Dynamic registration capacity manager

FlowCare now includes a backend-enforced daily registration session model for the Dynamic Registration Capacity Manager. The default seed config in `backend/app/main.py` creates a `Morning Registration` session for each date with `total_capacity = 30`, `initial_online_capacity = 12`, and `initial_physical_capacity = 18`. The session uses `Asia/Kolkata` time and lazily reconciles the cutoff at `10:00` before physical registration is accepted. Admin routes are available under `/api/admin/registration/sessions` and public booking routes under `/api/registration/...`.

### API contracts

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

| Method and route | Access | Purpose |
|---|---|---|
| `POST /api/auth/login`, `GET /api/auth/me` | public / staff | Login and current identity |
| `GET /api/departments`, `POST /api/departments` | staff / admin | List and create departments |
| `GET /api/staff`, `POST /api/staff`, `PATCH /api/staff/{department_id}/availability` | admin | Staff accounts and department capacity |
| `POST /api/patients` | admin, receptionist | Create synthetic patient and queue token |
| `GET /api/queue/current`, `GET /api/queue/tickets/{id}` | staff | Read queue |
| `PATCH /api/queue/tickets/{id}/status` | staff | Validated status transition |
| `POST /api/predictions/wait-time?ticket_id=...` | staff | Save and return one estimate |
| `GET /api/predictions/{id}`, `GET /api/predictions/evaluation` | staff | Prediction record and completed-case MAE |
| `POST /api/simulations/compare`, `GET /api/simulations/{id}/results` | admin / staff | Run and retrieve seeded scenario comparison |
| `GET /api/analytics/overview`, `/departments`, `/trends`, `/bottlenecks` | staff | Database-backed operations view |
| `GET /api/audit-logs` | admin | Recent audit actions |
| `GET /api/patient/tickets/{reference}` | reference holder | Narrow patient-safe status and wait estimate |

## Windows quick start

Requirements: Python 3.10+, Node.js 20+, npm, Git. Use two PowerShell terminals from the project root.

### 1. Backend (PowerShell)

```powershell
Copy-Item .env.example .env
$env:JWT_SECRET = [guid]::NewGuid().ToString() + [guid]::NewGuid().ToString()
$env:FLOWCARE_DEMO_PASSWORD = "Set-a-private-demo-password"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

The demo administrator is created only when `FLOWCARE_DEMO_PASSWORD` is set before the API starts:

- Email: `admin@flowcare.local`
- Password: the private value you chose in your shell (never commit it)

The server adds General Medicine, Cardiology, and Orthopedics demo departments. API docs: `http://localhost:8000/docs`; health: `http://localhost:8000/health`.

### 2. Frontend (second PowerShell)

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The frontend proxies API requests to `http://localhost:8000`. Sign in with the admin credentials configured above. Use the registration screen to issue a demo token; move it through **Start** and **Complete** in Live queue. Predictions are stored and compared against actual recorded waits after completion.

### 3. Tests

From the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest backend\tests -q
cd frontend
npm ci
npm test
npm run build
```

### 4. Train the optional model

```powershell
.\.venv\Scripts\Activate.ps1
python ml\generate_synthetic.py --seed 2025 --days 90
python ml\train.py
```

The generator writes event-level synthetic rows to `ml/data/generated/synthetic_events.csv`. The trainer sorts by time, trains on the first 80%, evaluates on the later 20%, compares MAE/RMSE with a queue-work baseline, saves a model under `ml/artifacts/`, and writes `evaluation.json`. The API loads the model artifact if present; without it, it explicitly reports `historical-median-baseline`. The synthetic training feature table includes queue size, staffing, busy servers, hour, and appointment status. Delete/regenerate artifacts as needed; they are excluded from Git. Report the JSON values as synthetic-only metrics.

### 5. Android APK from GitHub Actions

1. Create a new GitHub repository and upload/push the contents of this folder.
2. In GitHub, open **Actions** and enable workflows if prompted.
3. Optional but needed for a usable deployed mobile client: deploy the FastAPI service over HTTPS and add repository **Settings → Secrets and variables → Actions → Variables → New repository variable** with name `FLOWCARE_API_URL` and value such as `https://your-api.example.com`. Configure that server's allowed CORS origins, secret, persistent PostgreSQL, and HTTPS separately.
4. Run **Build Android APK** from Actions (or push to `main` / `master`). When complete, open its run, scroll to **Artifacts**, and download `flowcare-android-apk`. Extract `app-debug.apk` and install it on an Android test device.

The downloadable artifact is a debug APK, suitable for a student demonstration, not Play Store publication. Keep the backend API reachable by the phone. If `FLOWCARE_API_URL` is unset, the workflow still builds the APK, but it cannot connect to an API hosted on another machine. Do not put credentials in the GitHub variable.

GitHub needs `frontend/package-lock.json` for the reproducible `npm ci` workflow. Create it once after Node/npm are installed:

```powershell
cd frontend
npm install
git add package-lock.json
```

The project ZIP in this delivery contains source code; push its extracted contents, not the enclosing ZIP file, to GitHub.

### Optional Docker API

Copy `.env.example` to `.env`, set a long random `JWT_SECRET`, then run `docker compose up --build`. The compose service persists its SQLite file in a Docker volume. The React UI can run separately using the local steps above.

## Prediction methodology and limitations

The live estimator uses current active patients, number of staff available, elapsed service time and a department's median of up to 100 completed service durations. It dispatches queued work to the earliest available server rather than dividing total work by staff count. If there are no available staff, it returns no finite wait estimate and says so. The present queue does not model scheduled appointment order or staff break calendars.

For interpretability, the displayed range is estimate ± one typical service duration, clipped at zero. It is a planning range, **not a calibrated confidence/prediction interval**. An optional six-feature Random Forest uses only arrival-time available features, with a chronological holdout and persisted artifact. The demo training data is synthetic; using a trained model in production requires authorized observations, temporal validation, drift monitoring, calibration, and domain review.

The discrete-event scenario comparison uses a seeded shared arrival sequence and seeded service durations for both scenarios. Reported mean wait, p90 wait, queue length, throughput, and utilization are simulated measurements only. Bottleneck detection uses a configurable queue-size heuristic and explicitly does not establish a cause.

## Development status / known boundaries

The runnable MVP implements staff login/RBAC, token registration, queue transitions with timestamp/event history, one active consultation queue per ticket, a limited patient-reference status lookup, estimate persistence/evaluation, reproducible event-based simulation, live database analytics, threshold-based queue signals, department/staff administration, audit list, SQLite/Alembic migrations, React responsive interface, tests and APK workflow.

This is not the entire proposed hospital production system: patient self-service accounts/password login, multiple stage routing, appointment calendar, doctor-specific rosters/breaks, priority ordering, rate limiting, live WebSockets, persistent admin-managed alert acknowledgements, PostgreSQL CI integration, backups/retention, calibrated intervals and regulated clinical deployment require further implementation. In particular, `priority` is recorded but does not alter queue order or triage. Keep clinical decisions with authorized professionals.
