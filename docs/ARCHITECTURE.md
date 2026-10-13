# FlowCare architecture and implementation notes

## Data flow

React/Vite → FastAPI JSON API → SQLAlchemy session → SQLite (local) or PostgreSQL (deployment). Queue transitions append `queue_events`, preserve first-start/completion timestamps, and create audit rows. Prediction records retain a small feature/context snapshot and are matched to observed waits when a ticket completes. Analytics aggregate records from the API database, not presentation constants.

The optional model artifact is loaded from `ml/artifacts/wait_time_model.joblib`; a missing file uses a deterministic historical-median queue baseline. Model training is offline, temporal, repeatable, and evaluated against a transparent work-based baseline.

## Initial implementation phases

1. Requirements, architecture, initial relational schema, API boundaries and folders — documented here, in the README, and in Alembic revision `0001_initial`.
2. Backend, persistence, migration and environment-driven demonstration login.
3. Patient reference/token registration, queue lifecycle, status history and role checks.
4. Reproducible synthetic event generation, baseline estimate and optional model evaluation.
5. Prediction persistence and measured error calculation.
6. Seeded, event-based staffing scenario comparison.
7. React operational views, patient registration, queue, analytics and administration; Capacitor shell.
8. Unit/API tests and targeted build validation.
9. GitHub Actions APK artifact and setup documentation.

The current source implements an MVP across the phases. Extensions and not-yet-covered production requirements are listed in the root README rather than advertised as done.
