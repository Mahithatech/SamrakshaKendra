Samraksha Kendra — explicit NCDC approval and live promotion

PURPOSE
Promote only individually approved rows from public.ncdc_outbreak_staging into
public.idsp_surveillance. The default is dry-run; the original source CSV is not changed.

INSTALL
Copy tools\promote_ncdc_staging.py into the project's tools folder.
Copy ncdc_week1_approval_manifest_TEMPLATE.csv into data\ncdc_week1_approval_manifest.csv.
Do not overwrite an existing manifest; keep it as an audit artifact.

APPROVAL REQUIREMENTS
For each record you personally checked against the official report (and your supervisor
has approved for project testing), fill every approval field:
- approved_by: your reviewing/approving identity
- approved_at_utc: ISO timestamp with timezone, e.g. 2026-10-16T10:30:00+05:30
- source_pdf_checked: true
- approval_note: explain that case/death counts, state, district, disease and dates were checked
Rows with all approval fields blank are ignored. Partially completed approvals fail.
Do not bulk approve rows just to make the queue empty. Unknown numeric values stay unknown.

DRY RUN (no writes)
From project root:
.\backend\.venv\Scripts\python.exe .\tools\promote_ncdc_staging.py

LIVE APPLY (only after explicit source/supervisor review)
.\backend\.venv\Scripts\python.exe .\tools\promote_ncdc_staging.py --apply --confirm PROMOTE-APPROVED-NCDC-ROWS

The script checks official NCDC HTTPS PDF URLs, source-review status, case values, ISO week,
explicit per-record approvals, and skips already-live record IDs. It writes the report-year/week
as the ISO weekly reporting period (Monday–Sunday) and retains source provenance. Review the
source/model semantics before operational deployment. Staging records updated after successful
inserts are marked promoted_to_live_surveillance. No report PDF parsing is automatic here.
