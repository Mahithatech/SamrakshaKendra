# Samraksha Kendra
## Digital Disease Surveillance and Early Warning System for Public Health

Samraksha Kendra is a student-built public-health surveillance prototype that brings loaded disease-surveillance records into a dashboard and provides exploratory screening for unusual case counts.

### Current capabilities
- React and Vite web dashboard.
- FastAPI backend with interactive API documentation.
- PostgreSQL-backed surveillance data.
- Surveillance summary, state and disease aggregates, and weekly trend data.
- Exploratory historical anomaly screening using a trailing median and robust median absolute deviation (MAD).
- India outbreak-report and global-outbreak API endpoints.
- Hospital-directory data is available in the project database.

### Technology stack
- Frontend: React, Vite, JavaScript and CSS.
- Backend: Python, FastAPI and SQLAlchemy.
- Database: PostgreSQL.
- API testing: Swagger UI and HTTP requests.
- Version control: Git and GitHub.

### Run locally

#### Backend
Open PowerShell at the project root and run:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

API documentation: http://127.0.0.1:8000/docs

#### Frontend
Open a second PowerShell window:

```powershell
cd frontend-react
npm.cmd run dev
```

Open the local URL printed by Vite, normally http://localhost:5173.

To create a production build:

```powershell
npm.cmd run build
```

### Surveillance summary currently returned by this installation
- Loaded source records: 246
- Sum of source-row case counts: 7,133
- Sum of source-row death counts: 24
- State labels: 26
- Disease labels: 36

These figures describe the currently loaded records only. They do not establish exhaustive national coverage or unique case totals. Rows may overlap, and the data contains gaps between observed reporting periods.

### Exploratory anomaly screening
The API endpoint `/analytics/anomalies?min_history=2` supports exploratory screening with a short historical baseline. The current installation returns five candidates from 13 evaluable periods.

These results are not confirmed outbreaks or medical advice. Short histories can produce unreliable flags. Results require verification by qualified public-health personnel. A lack of flags does not prove that no outbreak exists.

### Data provenance and limitations
The project includes surveillance records and outbreak-related data staged in the `data` directory and database. For every dataset, document its original publisher, exact source URL, download date, reporting period, licence or terms of use, and any cleaning steps before claiming it is an official or complete dataset.

Disease labels with similar spelling or wording are currently kept separate until their definitions and source provenance have been checked.

### Privacy and security
Use public, authorized, or properly de-identified data for demonstrations. Do not commit passwords, database credentials, API keys, private patient data, or local environment files. Configure secrets through environment variables.

### Project status
This is a working prototype under development. Production deployment requires further validation of data quality, anomaly detection, access control, privacy, monitoring, and public-health workflows.

## Reviewer upgrade: secured login and live source refresh

- A single admin account is configured locally with `backend/setup_auth.py`. Passwords are hashed with Argon2; API access tokens expire after 45 minutes. There is no public registration.
- HTTP API routes require a bearer token except the login route and API documentation. The WebSocket alerts stream authenticates its first message without putting the token in the URL.
- The backend checks the WHO Disease Outbreak News publication feed and NCDC/IDSP weekly-report catalogue in the background every 15 minutes. `/system/source-status` reports source freshness and the structured surveillance row count.
- Important limitation: external WHO notices and NCDC PDF links are publication data; they are **not automatically converted to numeric case/death rows**. The 246 structured surveillance rows remain unchanged until each new report is parsed, reconciled, validated and explicitly imported. Feed refresh time is not the same as the source publication time.
- This is a local/reviewer prototype. For public deployment, use HTTPS, a production secret manager, persistent users/audit trails, and an external rate limiter.

