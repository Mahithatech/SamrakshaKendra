# Durable NCDC report review state

The signed-in administrator's NCDC **publication-link** review decisions are persisted in PostgreSQL and audit events are append-only. The local JSON file remains a cache/source-discovery queue; its loss on a Render redeploy no longer resets saved review status for matching stable report IDs.

## New database tables
- `ncdc_report_review_state`: current status, notes, reviewer, timestamps.
- `ncdc_report_review_audit`: append-only status/notes change history.

The API response shape remains compatible with the existing React queue. `GET /admin/ncdc-report-queue/audit` lists the latest audit events. A database error returns HTTP 503 rather than falsely reporting a durable review as saved.

This workflow tracks review of official PDF links only. It does **not** parse case counts, promote candidate rows, or modify `idsp_surveillance`. Use the validated staging/import workflow separately after field-by-field PDF verification.

## Apply and verify
Run the patch installer from the project root with the existing venv, then run:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests .\tools\test_promote_ncdc_staging.py -q
Remove-Item Env:PYTHONPATH
cd .\frontend-react
npm.cmd run build
```

Commit and push only after both checks pass. The existing FastAPI process needs a redeploy/restart for the changed code to take effect. The new tables are created additively on first queue access.
