$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dataDir = Join-Path $projectRoot 'data'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$preview = Join-Path $projectRoot 'tools\ncdc_preview_import.py'
$validator = Join-Path $projectRoot 'tools\validate_ncdc_staging.py'
$year = (Get-Date).Year
$candidate = Join-Path $dataDir "ncdc_latest_candidates_${year}_auto.csv"
$statusPath = Join-Path $dataDir 'ncdc_auto_refresh_status.json'
$logPath = Join-Path $dataDir 'ncdc_auto_refresh.log'

$status = [ordered]@{
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    finished_at_utc = $null
    status = 'running'
    report_year = $year
    reports_limit = 3
    candidate_csv = $candidate
    qa_csv = $candidate -replace '\.csv$', '_qa.csv'
    qa_summary_json = $candidate -replace '\.csv$', '_qa.summary.json'
    rows_examined = $null
    rows_needing_review = $null
    extraction_exit_code = $null
    validation_exit_code = $null
    database_modified = $false
    note = 'Candidate extraction and QA only. This task never writes to PostgreSQL or promotes records to live surveillance.'
    error = $null
}

try {
    if (!(Test-Path $python)) { throw "Project virtualenv Python not found: $python" }
    if (!(Test-Path $preview)) { throw "NCDC preview tool not found: $preview" }
    if (!(Test-Path $validator)) { throw "NCDC validator not found: $validator" }

    "[$([DateTime]::UtcNow.ToString('o'))] Starting NCDC candidate refresh for $year" | Add-Content -Path $logPath -Encoding UTF8
    & $python $preview --year $year --limit 3 --max-reports 3 --output $candidate 2>&1 | Tee-Object -FilePath $logPath -Append
    $extractCode = $LASTEXITCODE
    $status.extraction_exit_code = $extractCode
    if ($extractCode -ne 0) { throw "NCDC extraction failed with exit code $extractCode. Existing candidate files were not promoted." }
    if (!(Test-Path $candidate)) { throw "Extraction exited successfully but candidate CSV was not created." }

    & $python $validator $candidate 2>&1 | Tee-Object -FilePath $logPath -Append
    $validateCode = $LASTEXITCODE
    $status.validation_exit_code = $validateCode
    if ($validateCode -ne 0) { throw "NCDC candidate validation command failed with exit code $validateCode." }

    $summaryPath = $candidate -replace '\.csv$', '_qa.summary.json'
    if (Test-Path $summaryPath) {
        $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
        $status.rows_examined = $summary.rows_examined
        $status.rows_needing_review = $summary.rows_needing_review
        if ([int]$summary.rows_needing_review -gt 0) {
            $status.status = 'completed_with_review_flags'
        } else {
            $status.status = 'completed_needs_source_verification'
        }
    } else {
        $status.status = 'completed_needs_source_verification'
    }
}
catch {
    $status.status = 'failed'
    $status.error = $_.Exception.Message
    "[$([DateTime]::UtcNow.ToString('o'))] ERROR: $($_.Exception.Message)" | Add-Content -Path $logPath -Encoding UTF8
}
finally {
    $status.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    $status | ConvertTo-Json -Depth 5 | Set-Content -Path $statusPath -Encoding UTF8
    Write-Host "`nNCDC refresh status: $($status.status)"
    Write-Host "Status JSON: $statusPath"
    Write-Host "Log: $logPath"
    Write-Host 'Database modified: no'
    Write-Host 'Live surveillance updated: no'
}

if ($status.status -eq 'failed') { exit 1 }
