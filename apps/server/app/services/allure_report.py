"""Allure 2 results writer + HTML report generator.

Writes Allure-compatible JSON after each run; HTML is generated on demand via
the `allure` CLI. Shared by FastAPI routes and mcp-allure (via HTTP).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import ARTIFACTS_DIR, ROOT_DIR
from app.logging_setup import get_logger
from app.models.entities import CaseResult, Run

log = get_logger("allure")

ALLURE_INSTALL_HINT = (
    "未找到 allure CLI。请安装后重试：\n"
    "  推荐（项目内，需已装 Java 8+ / Node）：\n"
    "    Windows: .\\scripts\\windows\\install-allure.ps1\n"
    "    Linux:   ./scripts/linux/install-allure.sh\n"
    "    macOS:   ./scripts/macos/install-allure.sh\n"
    "  或全局: npm i -g allure-commandline@2.25.0\n"
    "  或见 https://docs.qameta.io/allure/#_installing_a_commandline"
)


def results_dir(run_id: int) -> Path:
    return ARTIFACTS_DIR / f"run-{run_id}" / "allure-results"


def report_dir(run_id: int) -> Path:
    return ARTIFACTS_DIR / f"run-{run_id}" / "allure-report"


def rel_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def results_url_path(run_id: int) -> str:
    return f"artifacts/run-{run_id}/allure-results"


def report_url_path(run_id: int) -> str:
    return f"artifacts/run-{run_id}/allure-report"


def report_index_url(run_id: int) -> str:
    return f"/artifacts/run-{run_id}/allure-report/index.html"


def _status_map(status: str) -> str:
    s = (status or "").lower()
    if s in {"passed", "pass", "success"}:
        return "passed"
    if s in {"failed", "fail", "error"}:
        return "failed"
    if s in {"skipped", "cancelled", "canceled", "broken"}:
        return "skipped" if s.startswith("skip") else "broken"
    if s == "broken":
        return "broken"
    return "unknown"


def _uuid() -> str:
    return uuid.uuid4().hex


def _copy_attachment(
    results: Path,
    source: Path,
    *,
    name: str,
    attachment_type: str,
) -> Optional[dict[str, str]]:
    if not source.exists() or not source.is_file():
        return None
    att_name = f"{_uuid()}-attachment{source.suffix or ''}"
    dest = results / att_name
    try:
        shutil.copy2(source, dest)
    except OSError:
        return None
    return {
        "name": name,
        "source": att_name,
        "type": attachment_type,
    }


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".png"}:
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext in {".webm"}:
        return "video/webm"
    if ext in {".mp4"}:
        return "video/mp4"
    if ext in {".txt", ".log"}:
        return "text/plain"
    return "application/octet-stream"


def write_results_for_run(run: Run, case_results: list[CaseResult] | None = None) -> str:
    """Write Allure results for a finished run. Returns relative results path."""
    crs = list(case_results if case_results is not None else (run.case_results or []))
    out = results_dir(run.id)
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    # environment.properties
    (out / "environment.properties").write_text(
        "\n".join(
            [
                f"RunId={run.id}",
                f"TaskId={run.task_id}",
                f"Status={run.status}",
                f"Total={run.total}",
                f"Passed={run.passed}",
                f"Failed={run.failed}",
                f"Skipped={run.skipped}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    suite_uuid = _uuid()
    children: list[str] = []
    finished = run.finished_at or datetime.now(timezone.utc).replace(tzinfo=None)
    stop_ms = int(
        finished.replace(tzinfo=timezone.utc).timestamp() * 1000
        if finished.tzinfo is None
        else finished.timestamp() * 1000
    )

    if not crs:
        # Minimal placeholder so MCP / UI still see a results dir.
        uid = _uuid()
        children.append(uid)
        start_ms = stop_ms - max(int(run.duration_ms or 0), 0)
        result = {
            "uuid": uid,
            "historyId": f"run-{run.id}-empty",
            "name": f"Run #{run.id} (no case results)",
            "fullName": f"tdashboard.Run.{run.id}.empty",
            "status": _status_map(run.status if run.status != "passed" else "skipped"),
            "statusDetails": {
                "message": run.error_summary or "No case results recorded",
            },
            "stage": "finished",
            "start": start_ms,
            "stop": stop_ms,
            "labels": [
                {"name": "suite", "value": f"Run #{run.id}"},
                {"name": "framework", "value": "tdashboard"},
                {"name": "language", "value": "python"},
            ],
            "steps": [],
            "attachments": [],
            "parameters": [],
        }
        (out / f"{uid}-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        # Spread case durations backwards from run finish.
        cursor = stop_ms
        for cr in reversed(crs):
            uid = _uuid()
            children.append(uid)
            dur = max(int(cr.duration_ms or 0), 0)
            case_stop = cursor
            case_start = case_stop - dur
            cursor = case_start

            steps_out: list[dict[str, Any]] = []
            step_cursor = case_start
            for step in cr.step_results or []:
                s_dur = max(int(step.get("duration_ms") or 0), 0)
                s_start = step_cursor
                s_stop = s_start + s_dur
                step_cursor = s_stop
                steps_out.append(
                    {
                        "name": step.get("name") or step.get("action") or "step",
                        "status": _status_map(str(step.get("status") or "passed")),
                        "statusDetails": (
                            {"message": step.get("error")} if step.get("error") else {}
                        ),
                        "stage": "finished",
                        "start": s_start,
                        "stop": s_stop,
                        "steps": [],
                        "attachments": [],
                        "parameters": [
                            {"name": "action", "value": str(step.get("action") or "")},
                        ],
                    }
                )

            attachments: list[dict[str, str]] = []
            seen_paths: set[str] = set()
            artifact_list = list(cr.artifacts or [])
            if cr.screenshot_path:
                artifact_list.append(
                    {
                        "type": "screenshot",
                        "path": cr.screenshot_path,
                        "label": "失败截图",
                    }
                )
            for art in artifact_list:
                rel = str(art.get("path") or "").replace("\\", "/").lstrip("/")
                if not rel or rel in seen_paths:
                    continue
                seen_paths.add(rel)
                src = ARTIFACTS_DIR / rel
                if not src.exists():
                    # path may already include run-N/case-N
                    alt = ROOT_DIR / rel
                    src = alt if alt.exists() else src
                label = str(art.get("label") or art.get("type") or src.name)
                mime = _mime_for(src)
                copied = _copy_attachment(out, src, name=label, attachment_type=mime)
                if copied:
                    attachments.append(copied)

            status = _status_map(cr.status)
            if cr.status and cr.status.lower() in {"cancelled", "canceled"}:
                status = "skipped"

            result = {
                "uuid": uid,
                "historyId": f"case-{cr.case_id}",
                "testCaseId": f"case-{cr.case_id}",
                "name": cr.case_name or f"Case {cr.case_id}",
                "fullName": f"tdashboard.Case.{cr.case_id}",
                "status": status,
                "statusDetails": {
                    "message": cr.error_message or "",
                    "trace": cr.error_type or "",
                },
                "stage": "finished",
                "start": case_start,
                "stop": case_stop,
                "labels": [
                    {"name": "suite", "value": f"Run #{run.id}"},
                    {"name": "package", "value": "tdashboard"},
                    {"name": "testClass", "value": f"Case{cr.case_id}"},
                    {"name": "testMethod", "value": cr.case_name or str(cr.case_id)},
                    {"name": "framework", "value": "tdashboard"},
                    {"name": "language", "value": "python"},
                    {"name": "tag", "value": f"run-{run.id}"},
                ],
                "steps": steps_out,
                "attachments": attachments,
                "parameters": [
                    {"name": "case_id", "value": str(cr.case_id)},
                    {"name": "run_id", "value": str(run.id)},
                ],
            }
            (out / f"{uid}-result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        children.reverse()  # restore chronological order for container

    container = {
        "uuid": suite_uuid,
        "name": f"Run #{run.id}",
        "children": children,
        "befores": [],
        "afters": [],
        "start": stop_ms - max(int(run.duration_ms or 0), 0),
        "stop": stop_ms,
    }
    (out / f"{suite_uuid}-container.json").write_text(
        json.dumps(container, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # executor.json for nicer report header
    (out / "executor.json").write_text(
        json.dumps(
            {
                "name": "T-Dashboard",
                "type": "tdashboard",
                "buildName": f"Run #{run.id}",
                "buildOrder": run.id,
                "reportName": f"T-Dashboard Run #{run.id}",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return results_url_path(run.id)


def _allure_candidates() -> list[Path]:
    """Prefer real dist/bin wrappers; avoid npm .bin shim (Node 20+ spawn EINVAL on Win)."""
    names = ("allure.bat", "allure") if os.name == "nt" else ("allure",)
    bases = [
        ROOT_DIR / "tools" / "allure" / "node_modules" / "allure-commandline",
    ]
    out: list[Path] = []
    for base in bases:
        for name in names:
            out.append(base / "dist" / "bin" / name)
            out.append(base / "bin" / name)
    return out


def find_allure_cli() -> Optional[str]:
    """Locate allure binary: ALLURE_CLI env, project tools/, PATH, npm global."""
    env_cli = (os.environ.get("ALLURE_CLI") or "").strip()
    if env_cli and Path(env_cli).exists():
        return env_cli

    for candidate in _allure_candidates():
        if candidate.exists():
            return str(candidate)

    which = shutil.which("allure")
    if which:
        # Skip broken npm shim that is a .js/.cmd wrapping node spawn
        lower = which.lower()
        if lower.endswith(".js"):
            pass
        else:
            return which

    try:
        completed = subprocess.run(
            ["npm", "root", "-g"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=(os.name == "nt"),
        )
        if completed.returncode == 0:
            root = Path((completed.stdout or "").strip())
            pkg = root / "allure-commandline"
            for name in (("allure.bat", "allure") if os.name == "nt" else ("allure",)):
                for rel in (Path("dist") / "bin" / name, Path("bin") / name):
                    candidate = pkg / rel
                    if candidate.exists():
                        return str(candidate)
    except Exception:  # noqa: BLE001
        pass

    return None


def generate_html(run_id: int) -> dict[str, Any]:
    """Generate Allure HTML report from existing results. Raises ValueError on failure."""
    results = results_dir(run_id)
    if not results.exists() or not any(results.glob("*-result.json")):
        raise ValueError(f"Run #{run_id} 尚无 allure-results，请先完成一次运行。")

    cli = find_allure_cli()
    if not cli:
        log.error("allure CLI missing for run_id=%s", run_id)
        raise RuntimeError(ALLURE_INSTALL_HINT)

    out = report_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    log.info("allure generate run_id=%s cli=%s out=%s", run_id, cli, out)
    completed = subprocess.run(
        [cli, "generate", str(results), "-o", str(out), "--clean"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        log.error("allure generate failed run_id=%s err=%s", run_id, err or completed.returncode)
        raise RuntimeError(f"allure generate 失败: {err or completed.returncode}")

    index = out / "index.html"
    if not index.exists():
        raise RuntimeError("allure generate 完成但未找到 index.html")

    log.info("allure report ready run_id=%s url=%s", run_id, report_index_url(run_id))
    return {
        "ok": True,
        "run_id": run_id,
        "results_path": results_url_path(run_id),
        "report_path": report_url_path(run_id),
        "report_url": report_index_url(run_id),
    }


def get_report_paths(run_id: int) -> dict[str, Any]:
    results = results_dir(run_id)
    report = report_dir(run_id)
    has_results = results.exists() and any(results.glob("*-result.json"))
    has_report = (report / "index.html").exists()
    return {
        "run_id": run_id,
        "has_results": has_results,
        "has_report": has_report,
        "results_path": results_url_path(run_id) if has_results else None,
        "report_path": report_url_path(run_id) if has_report else None,
        "report_url": report_index_url(run_id) if has_report else None,
        "allure_cli": bool(find_allure_cli()),
    }


def summarize_run(run: Run) -> dict[str, Any]:
    paths = get_report_paths(run.id)
    failed = [
        {
            "case_id": cr.case_id,
            "case_name": cr.case_name,
            "status": cr.status,
            "error_message": cr.error_message,
            "error_type": cr.error_type,
            "screenshot_path": cr.screenshot_path,
            "artifacts": cr.artifacts or [],
            "duration_ms": cr.duration_ms,
        }
        for cr in (run.case_results or [])
        if (cr.status or "").lower() in {"failed", "broken", "error"}
    ]
    total = run.total or len(run.case_results or [])
    passed = run.passed
    failed_n = run.failed
    skipped = run.skipped
    pass_rate = (passed / total * 100.0) if total else 0.0
    return {
        **paths,
        "status": run.status,
        "total": total,
        "passed": passed,
        "failed": failed_n,
        "skipped": skipped,
        "duration_ms": run.duration_ms,
        "pass_rate": round(pass_rate, 2),
        "error_summary": run.error_summary or "",
        "failed_cases": failed,
    }
