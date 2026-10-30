"""mcp-playwright: stdio MCP tools over T-Dashboard HTTP API (run Playwright cases)."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_API = "http://127.0.0.1:8000"

mcp = FastMCP(
    "mcp-playwright",
    instructions=(
        "Run and inspect Playwright automation via T-Dashboard. "
        "List projects/cases, start runs, poll status, cancel runs. "
        "Requires the T-Dashboard API (default http://127.0.0.1:8000). "
        "For Allure reports use the separate mcp-allure server."
    ),
)


def _base_url() -> str:
    return os.environ.get("TDASHBOARD_API", DEFAULT_API).rstrip("/")


def _client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def _get(path: str, **params: Any) -> Any:
    url = f"{_base_url()}{path}"
    with _client() as client:
        res = client.get(url, params={k: v for k, v in params.items() if v is not None})
        if res.status_code >= 400:
            raise RuntimeError(f"GET {path} -> {res.status_code}: {res.text}")
        return res.json()


def _post(path: str, body: dict[str, Any] | None = None, *, timeout: float = 180.0) -> Any:
    url = f"{_base_url()}{path}"
    with _client(timeout=timeout) as client:
        res = client.post(url, json=body if body is not None else None)
        if res.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {res.status_code}: {res.text}")
        if res.status_code == 204 or not res.content:
            return {"ok": True}
        return res.json()


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def playwright_health() -> str:
    """Check T-Dashboard API health and Playwright Chromium install status."""
    health = _get("/api/health")
    try:
        pw = _get("/api/playwright/status")
    except Exception as exc:  # noqa: BLE001
        pw = {"error": str(exc)}
    return _dumps({"api": _base_url(), "health": health, "playwright": pw})


@mcp.tool()
def playwright_list_projects() -> str:
    """List all T-Dashboard projects (id, name, base_url)."""
    projects = _get("/api/projects")
    rows = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "base_url": p.get("base_url"),
            "description": p.get("description"),
            "default_browser": p.get("default_browser"),
        }
        for p in projects
    ]
    return _dumps({"projects": rows})


@mcp.tool()
def playwright_list_cases(project_id: int) -> str:
    """List cases in a project (id, name, mode, enabled, tags).

    Args:
        project_id: Project id.
    """
    cases = _get(f"/api/projects/{int(project_id)}/cases")
    rows = [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "mode": c.get("mode"),
            "enabled": c.get("enabled"),
            "tags": c.get("tags") or [],
            "steps_count": len(c.get("steps") or []),
            "description": c.get("description") or "",
        }
        for c in cases
    ]
    return _dumps({"project_id": int(project_id), "cases": rows})


@mcp.tool()
def playwright_get_case(case_id: int) -> str:
    """Get full case detail including steps and script metadata.

    Args:
        case_id: Case id.
    """
    case = _get(f"/api/cases/{int(case_id)}")
    return _dumps(case)


@mcp.tool()
def playwright_list_tasks(project_id: int) -> str:
    """List tasks for a project.

    Args:
        project_id: Project id.
    """
    tasks = _get(f"/api/projects/{int(project_id)}/tasks")
    return _dumps({"project_id": int(project_id), "tasks": tasks})


@mcp.tool()
def playwright_run_cases(
    project_id: int,
    case_ids: list[int],
    task_name: str = "",
    headless: bool = True,
    browser: str = "chromium",
    timeout_ms: int = 30000,
    capture_screenshots: bool = False,
    record_video: bool = False,
) -> str:
    """Create a task from selected cases and start a Playwright run immediately.

    Args:
        project_id: Project id.
        case_ids: Case ids to execute (order preserved).
        task_name: Optional task name (default auto).
        headless: Run browser headless (default True). Set False to watch the window.
        browser: Browser engine: chromium | firefox | webkit.
        timeout_ms: Default step timeout.
        capture_screenshots: Capture screenshots on DOM/nav changes.
        record_video: Record video for the run.
    """
    if not case_ids:
        raise ValueError("case_ids must not be empty")
    name = (task_name or "").strip() or f"MCP run {','.join(str(i) for i in case_ids)}"
    body = {
        "name": name,
        "case_ids": [int(i) for i in case_ids],
        "browser": browser or "chromium",
        "headless": bool(headless),
        "timeout_ms": int(timeout_ms),
        "capture_screenshots": bool(capture_screenshots),
        "record_video": bool(record_video),
        "run_immediately": True,
    }
    result = _post(f"/api/projects/{int(project_id)}/tasks", body)
    run = result.get("run") or {}
    task = result.get("task") or {}
    return _dumps(
        {
            "message": "Run enqueued. Poll with playwright_get_run until status is terminal.",
            "task_id": task.get("id"),
            "run_id": run.get("id"),
            "status": run.get("status"),
            "task": task,
            "run": run,
        }
    )


@mcp.tool()
def playwright_run_task(task_id: int) -> str:
    """Re-run an existing task (creates a new Run).

    Args:
        task_id: Existing task id.
    """
    run = _post(f"/api/tasks/{int(task_id)}/run")
    return _dumps(
        {
            "message": "Run enqueued. Poll with playwright_get_run until finished.",
            "run_id": run.get("id"),
            "status": run.get("status"),
            "run": run,
        }
    )


@mcp.tool()
def playwright_list_runs(limit: int = 20, project_id: int | None = None) -> str:
    """List recent runs (status, pass/fail counts).

    Args:
        limit: Max runs (1-100).
        project_id: Optional project filter.
    """
    limit = max(1, min(int(limit), 100))
    runs = _get("/api/runs", limit=limit, project_id=project_id)
    rows = [
        {
            "run_id": r.get("id"),
            "task_id": r.get("task_id"),
            "task_name": r.get("task_name"),
            "project_name": r.get("project_name"),
            "status": r.get("status"),
            "passed": r.get("passed"),
            "failed": r.get("failed"),
            "skipped": r.get("skipped"),
            "total": r.get("total"),
            "duration_ms": r.get("duration_ms"),
            "created_at": r.get("created_at"),
        }
        for r in runs
    ]
    return _dumps({"runs": rows})


@mcp.tool()
def playwright_get_run(run_id: int) -> str:
    """Get run detail: status, case results, step outcomes, artifacts, logs summary.

    Args:
        run_id: Run id.
    """
    run = _get(f"/api/runs/{int(run_id)}")
    # Trim huge logs for model context; keep last 40 lines.
    logs = run.get("logs") or []
    if isinstance(logs, list) and len(logs) > 40:
        run = {**run, "logs": logs[-40:], "logs_truncated": True, "logs_total": len(logs)}
    return _dumps(run)


@mcp.tool()
def playwright_cancel_run(run_id: int) -> str:
    """Cancel a pending/running run (terminates worker + browser).

    Args:
        run_id: Run id.
    """
    return _dumps(_post(f"/api/runs/{int(run_id)}/cancel"))


@mcp.tool()
def playwright_analytics(project_id: int | None = None) -> str:
    """Get analytics summary (pass rate, failure types, slow cases).

    Args:
        project_id: Optional project filter.
    """
    return _dumps(_get("/api/analytics/summary", project_id=project_id))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
