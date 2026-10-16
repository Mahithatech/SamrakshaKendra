# NCDC report review queue

This feature turns the official NCDC/IDSP weekly report catalogue into a persistent review workflow.

## What happens automatically
- The existing FastAPI background task checks the official publication catalogue on its existing 15-minute schedule.
- Newly discovered HTTPS PDF links on `ncdc.mohfw.gov.in` are added to `data/ncdc_report_review_queue.json` with a stable ID, source URL, title, year/week when supplied, first/last seen timestamps and `pending_review` status.
- Repeated feeds do not create duplicate queue entries and do not overwrite review decisions or notes.
- The React page polls the protected queue endpoint while open and lets the signed-in admin mark a report reviewed, ignored or reopen it.

## Critical limit
This is **publication discovery and human review**, not automatic case-count extraction. Marking a document reviewed does not alter PostgreSQL surveillance rows. After checking a PDF, any numerical rows still need to be extracted, reconciled against the source, validated in staging and imported through the existing validated import process. Never turn a missing number into zero or publish inferred case counts as official data.

## Endpoints
- `GET /admin/ncdc-report-queue?status=pending_review&limit=200`
- `POST /admin/ncdc-report-queue/items/{report_id}/review` with JSON `{"status":"reviewed","notes":"Checked PDF source and reporting week"}`

All routes rely on the existing bearer-token middleware; keep `.env` private. The queue file is local app metadata, not patient data.

## Tests
From project root, run with the backend virtual environment:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install pytest
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests\test_report_review_queue.py
```

Then return to the project root and run the frontend build:

```powershell
cd ..
cd frontend-react
npm.cmd run build
```
