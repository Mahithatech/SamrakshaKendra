SAMRAKSHA KENDRA — EXPLICIT NCDC PROMOTION WORKFLOW

Copy the contents of this archive (tools/, data/, docs/) into the root of:
C:\Users\Mahit\SamrakshaKendra

If data\ncdc_week1_approval_manifest.csv does not already exist, copy:
data\ncdc_week1_approval_manifest_TEMPLATE.csv
into data\ncdc_week1_approval_manifest.csv. Keep the template file as-is.

1) Run unit tests:
.\backend\.venv\Scripts\python.exe -m unittest discover -s .\tools -p "test_promote_ncdc_staging.py" -v

2) The approval manifest intentionally has blank approval fields. Do not fill them until each row's fields have been checked against the official NCDC PDF and approved for the project. Fill the following for each row approved for promotion:
- approved_by: reviewer/approver name or role
- approved_at_utc: ISO timestamp including timezone (e.g. 2026-10-16T10:30:00+05:30)
- source_pdf_checked: true
- approval_note: substantive note confirming state/district/disease/cases/deaths and dates were checked

3) Dry-run, no database writes:
.\backend\.venv\Scripts\python.exe .\tools\promote_ncdc_staging.py

4) Live insert requires all records to have explicit manifest approvals and both flags:
.\backend\.venv\Scripts\python.exe .\tools\promote_ncdc_staging.py --apply --confirm PROMOTE-APPROVED-NCDC-ROWS

The script promotes only approved rows. Rows without complete approval are ignored; partial approvals fail. It skips record IDs already in idsp_surveillance. It never infers a missing case count. Existing staging values and statuses change only for rows successfully inserted into live surveillance. Review the project's week/date semantics before operational use. Automatic PDF extraction is not implemented by this tool.
