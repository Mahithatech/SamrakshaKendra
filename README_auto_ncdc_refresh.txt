Samraksha Kendra — automatic NCDC candidate refresh

Purpose
- Runs the existing NCDC PDF preview extractor for up to 3 reports for the current year.
- Runs the existing staging QA validator on the output.
- Writes data/ncdc_auto_refresh_status.json and data/ncdc_auto_refresh.log.
- Optionally registers a Windows Task Scheduler job daily at 06:30 local time.

Important safety boundary
- This is candidate extraction/QA only.
- It NEVER writes to PostgreSQL, approves data, or updates live surveillance.
- All PDF-extracted values still need source verification; QA flags are not the same as approval.
- It is not a continuous case-count feed; the NCDC archive updates when reports are published.

Install
1. Extract this ZIP into C:\Users\Mahit\SamrakshaKendra (preserve the tools folder structure).
2. In PowerShell:
   cd C:\Users\Mahit\SamrakshaKendra
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\refresh_ncdc_candidates.ps1
3. Inspect the status JSON and log at data\ncdc_auto_refresh_status.json and data\ncdc_auto_refresh.log.
4. To schedule a daily run at 06:30 while your Windows account is signed in:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\register_ncdc_refresh_task.ps1
5. To run the scheduled task immediately:
   Start-ScheduledTask -TaskName "SamrakshaKendra-NCDC-Candidate-Refresh"

Unregister scheduled task
  Unregister-ScheduledTask -TaskName "SamrakshaKendra-NCDC-Candidate-Refresh" -Confirm:$false

Note
The script overwrites its specifically named annual candidate CSV and validator-generated QA outputs on each run. Original one-off source-reviewed CSVs and PostgreSQL records are not touched.
