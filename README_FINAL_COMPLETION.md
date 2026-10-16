# Samraksha Kendra — core MVP completion kit

This patch closes a known deployment reliability gap and provides a repeatable end-to-end acceptance test.

## What it does
- Persists NCDC report-link review decisions in PostgreSQL and records changes in an append-only audit table. A Render redeploy no longer loses review state for matching stable report IDs.
- Adds unit tests for persistence/restart behavior.
- Adds GitHub Actions CI for backend tests and frontend production build.
- Offers an optional one-time migration of local NCDC candidates into the hosted **staging table only**.
- Runs a live acceptance check after Render publishes the new backend version, including one clearly labeled synthetic WebSocket event. That event is broadcast-only and is not stored as a surveillance record.

## Install with one script
1. Download `SamrakshaKendra_FinalCompletionKit.zip`.
2. Extract its contents directly into `C:\Users\Mahit\SamrakshaKendra` (merge folders; don't extract inside a subfolder).
3. Run this from PowerShell at the project root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Finish_SamrakshaKendra.ps1
```

The script makes a timestamped backup, applies the patch, compiles the backend, runs pytest and builds the frontend. If these checks pass, it commits/pushes the code and waits for Render's new audit endpoint before running the live test. It never stages `.env` or candidate CSV files.

When prompted about the staging copy, type `Y` to copy the local NCDC candidate records to `public.ncdc_outbreak_staging` only. This deliberately does not write to `idsp_surveillance` or live totals. The migration uses hidden input for Render's **External Database URL** and refuses to copy if the hosted staging table is non-empty or required columns cannot be preserved.

The live acceptance check asks for the admin username and a hidden password. It never prints the password or access token. It tests login, key protected APIs and a synthetic WebSocket alert.

## Scope note
This hardens the deployed **web MVP**. It does not add unimplemented mobile, MobileNetV2/image classification, RAG/AI assistant or full multilingual functionality. Those require separate implementation and verification; don't present them as complete until built and tested.
