# mcp-allure

MCP server that lets models query and generate **Allure** reports for [T-Dashboard](../README.md) runs.

Tools call the local T-Dashboard HTTP API (default `http://127.0.0.1:8000`).

## Tools

| Tool | Description |
|------|-------------|
| `allure_list_runs` | Recent runs + whether results/report exist |
| `allure_get_summary` | Pass rate, counts, failed cases, paths |
| `allure_generate_report` | Run `allure generate` for a run |
| `allure_get_report_url` | Report URL (generate if missing) |
| `allure_get_failed_cases` | Failed cases + errors + artifacts |

## Prerequisites

1. T-Dashboard API running (`uvicorn` on `:8000`)
2. Allure CLI installed on the **API host** (for HTML generation):
   - Windows (scoop): `scoop install allure`
   - Windows (choco): `choco install allure-commandline`
   - See [Allure docs](https://docs.qameta.io/allure/#_installing_a_commandline)

## Install

```powershell
cd mcp-allure
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# or: pip install -e .
```

## Cursor MCP config

Add to Cursor MCP settings (e.g. `.cursor/mcp.json` or user MCP config):

```json
{
  "mcpServers": {
    "mcp-allure": {
      "command": "C:/personsal/software/T-Dashboard/mcp-allure/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_allure.server"],
      "env": {
        "TDASHBOARD_API": "http://127.0.0.1:8000"
      }
    }
  }
}
```

Adjust the `command` path to your machine. Ensure `mcp-allure` is on `PYTHONPATH` or installed editable (`pip install -e .`) so `-m mcp_allure.server` resolves.

Alternative after `pip install -e .`:

```json
{
  "mcpServers": {
    "mcp-allure": {
      "command": "C:/personsal/software/T-Dashboard/mcp-allure/.venv/Scripts/mcp-allure.exe",
      "env": {
        "TDASHBOARD_API": "http://127.0.0.1:8000"
      }
    }
  }
}
```

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `TDASHBOARD_API` | `http://127.0.0.1:8000` | T-Dashboard base URL |

## Flow

1. Run cases in T-Dashboard → server writes `artifacts/run-{id}/allure-results/`
2. Model/UI calls `allure_generate_report` / opens **Allure 报告** → HTML at `/artifacts/run-{id}/allure-report/index.html`
