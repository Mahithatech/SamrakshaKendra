SAMRAKSHA KENDRA — EVIDENCE ASSISTANT PATCH

Adds a source-linked, retrieval-and-aggregation assistant for the structured IDSP surveillance data.
Supported questions include:
- Summarize the surveillance dataset
- Which diseases have the highest reported cases?
- Show weekly trend
- total cases in Karnataka
- dengue in Kerala

Answers include source endpoints/source URLs and a data-coverage disclaimer. The assistant is deterministic and database-grounded; it is NOT an LLM-generated RAG chatbot and is not clinical advice or an outbreak declaration system.

INSTALL
1. Download SamrakshaKendra_Evidence_Assistant.zip into Downloads.
2. Open PowerShell and run:

  cd C:\Users\Mahit\SamrakshaKendra
  Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\SamrakshaKendra_Evidence_Assistant.zip" -DestinationPath . -Force
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Finish_Evidence_Assistant.ps1

The script backs up files, applies the feature, compiles the backend, runs automated tests, checks OpenAPI with warnings treated as errors, builds the frontend, then commits and pushes only implementation files. It refuses if other Git changes are already staged.

After Render auto-deploys, open the app, sign in, and choose “Evidence assistant”. Suggested tests: “Summarize the surveillance dataset”, “Which diseases have the highest reported cases?”, “Show weekly trend”, “total cases in Karnataka”, “dengue in Kerala”. Check source links and the coverage disclaimer.

No API keys or additional paid model is needed. No records are inserted/changed by the assistant. Unverified NCDC candidates remain separate from live surveillance.
