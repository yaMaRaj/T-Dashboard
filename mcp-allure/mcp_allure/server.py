"""mcp-allure: stdio MCP tools over T-Dashboard HTTP API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_API = "http://127.0.0.1:8000"

mcp = FastMCP(
    "mcp-allure",
    instructions=(
        "Query and generate Allure reports for T-Dashboard Playwright runs. "
        "Requires the T-Dashboard API (default http://127.0.0.1:8000) to be running."
    ),
)


def _base_url() -> str:
    return os.environ.get("TDASHBOARD_API", DEFAULT_API).rstrip("/")


def _get(path: str, **params: Any) -> Any:
    url = f"{_base_url()}{path}"
    with httpx.Client(timeout=60.0) as client:
        res = client.get(url, params={k: v for k, v in params.items() if v is not None})
        if res.status_code >= 400:
            raise RuntimeError(f"GET {path} -> {res.status_code}: {res.text}")
        return res.json()


def _post(path: str) -> Any:
    url = f"{_base_url()}{path}"
    with httpx.Client(timeout=180.0) as client:
        res = client.post(url)
        if res.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {res.status_code}: {res.text}")
        return res.json()


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def allure_list_runs(limit: int = 20, project_id: int | None = None) -> str:
    """List recent T-Dashboard runs and whether Allure results/report exist.

    Args:
        limit: Max runs to return (1-100).
        project_id: Optional project filter.
    """
    limit = max(1, min(int(limit), 100))
    runs = _get("/api/runs", limit=limit, project_id=project_id)
    rows = []
    for r in runs:
        rid = r["id"]
        has_results = bool(r.get("allure_results_path"))
        has_report = bool(r.get("allure_report_path"))
        # Prefer live filesystem status when paths empty (legacy runs).
        if not has_results or not has_report:
            try:
                st = _get(f"/api/runs/{rid}/allure")
                has_results = bool(st.get("has_results"))
                has_report = bool(st.get("has_report"))
            except Exception:  # noqa: BLE001
                pass
        rows.append(
            {
                "run_id": rid,
                "status": r.get("status"),
                "task_name": r.get("task_name"),
                "project_name": r.get("project_name"),
                "passed": r.get("passed"),
                "failed": r.get("failed"),
                "skipped": r.get("skipped"),
                "total": r.get("total"),
                "duration_ms": r.get("duration_ms"),
                "has_results": has_results,
                "has_report": has_report,
                "created_at": r.get("created_at"),
            }
        )
    return _dumps({"api": _base_url(), "runs": rows})


@mcp.tool()
def allure_get_summary(run_id: int) -> str:
    """Get Allure/run summary for a run: pass rate, counts, failed cases, report paths.

    Args:
        run_id: T-Dashboard run id.
    """
    return _dumps(_get(f"/api/runs/{int(run_id)}/allure"))


@mcp.tool()
def allure_generate_report(run_id: int) -> str:
    """Generate Allure HTML report for a run (requires allure CLI on the API host).

    Args:
        run_id: T-Dashboard run id.
    """
    return _dumps(_post(f"/api/runs/{int(run_id)}/allure/generate"))


@mcp.tool()
def allure_get_report_url(run_id: int) -> str:
    """Return the Allure HTML report URL/path for a run. Generates the report if missing.

    Args:
        run_id: T-Dashboard run id.
    """
    run_id = int(run_id)
    status = _get(f"/api/runs/{run_id}/allure")
    if status.get("report_url"):
        return _dumps(
            {
                "run_id": run_id,
                "report_url": status["report_url"],
                "report_path": status.get("report_path"),
                "absolute_hint": f"{_base_url()}{status['report_url']}",
                "generated": False,
            }
        )
    generated = _post(f"/api/runs/{run_id}/allure/generate")
    return _dumps(
        {
            "run_id": run_id,
            "report_url": generated.get("report_url"),
            "report_path": generated.get("report_path"),
            "absolute_hint": f"{_base_url()}{generated.get('report_url')}",
            "generated": True,
        }
    )


@mcp.tool()
def allure_get_failed_cases(run_id: int) -> str:
    """List failed cases for a run with error messages and artifact paths.

    Args:
        run_id: T-Dashboard run id.
    """
    return _dumps(_get(f"/api/runs/{int(run_id)}/allure/failed-cases"))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
