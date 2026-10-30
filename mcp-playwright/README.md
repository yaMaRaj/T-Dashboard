# mcp-playwright

MCP server that lets models **run and inspect Playwright automation** through [T-Dashboard](../README.md).

Tools call the local T-Dashboard HTTP API (default `http://127.0.0.1:8000`).

For Allure HTML reports, use the sibling server [`mcp-allure`](../mcp-allure/).

## Tools

| Tool | Description |
|------|-------------|
| `playwright_health` | API health + Chromium install status |
| `playwright_list_projects` | List projects |
| `playwright_list_cases` | List cases in a project |
| `playwright_get_case` | Case detail (steps / script) |
| `playwright_list_tasks` | List tasks in a project |
| `playwright_run_cases` | Create task + start run immediately |
| `playwright_run_task` | Re-run an existing task |
| `playwright_list_runs` | Recent runs |
| `playwright_get_run` | Run detail (results, artifacts, logs) |
| `playwright_cancel_run` | Cancel a running/pending run |
| `playwright_analytics` | Pass rate / failure / slow-case summary |

## Prerequisites

1. T-Dashboard API running (`uvicorn` on `:8000`)
2. Playwright Chromium installed in the server venv (`python -m playwright install chromium`)

## Install

```powershell
cd mcp-playwright
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

## Cursor MCP config

```json
{
  "mcpServers": {
    "mcp-playwright": {
      "command": "C:/personsal/software/T-Dashboard/mcp-playwright/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_playwright"],
      "cwd": "C:/personsal/software/T-Dashboard/mcp-playwright",
      "env": {
        "TDASHBOARD_API": "http://127.0.0.1:8000"
      }
    }
  }
}
```

See also [`mcp.json.example`](mcp.json.example) (includes both playwright + allure).

## Typical agent flow

1. `playwright_list_projects` → pick `project_id`
2. `playwright_list_cases` → pick `case_ids`
3. `playwright_run_cases` → get `run_id`
4. Poll `playwright_get_run` until `status` is `passed` / `failed` / `cancelled`
5. Optionally call **mcp-allure** `allure_generate_report` / `allure_get_summary`

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `TDASHBOARD_API` | `http://127.0.0.1:8000` | T-Dashboard base URL |
