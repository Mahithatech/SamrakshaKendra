# Evidence Assistant

## Purpose
The Evidence Assistant provides source-linked question answering over the structured IDSP records already loaded into Samraksha Kendra. It supports aggregate summaries, state/disease filters, top disease/state summaries, and recent reporting-week trends. It returns a dataset coverage disclaimer and source references.

## Endpoint
`POST /public/assistant/query`

Request body:

```json
{
  "question": "total cases in Karnataka",
  "language": "en"
}
```

Supported `language` values: `en`, `te`, `kn`, `hi`.

## Important scope boundary
This is a deterministic retrieval-and-aggregation assistant, not an LLM-generated RAG chatbot. It queries available structured IDSP database rows and formats the results. It does not provide clinical advice, predict an outbreak, or invent missing counts. Answers reflect the loaded dataset only. The official WHO/NCDC publication feeds remain separate from structured count data.

## Manual smoke test
Open API docs and use `POST /public/assistant/query` with one of these examples:
- `Summarize the surveillance dataset`
- `Which diseases have the highest reported cases?`
- `Show weekly trend`
- `total cases in Karnataka`
- `dengue in Kerala`

Check the response for `answer`, `items`, `sources` and `disclaimer`.

## Tests
Run from the project root with backend import path set:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_evidence_assistant.py -q
Remove-Item Env:PYTHONPATH
```
