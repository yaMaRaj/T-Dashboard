"""HTTP APIs for run history, cancel, and Allure report generation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.logging_setup import get_logger
from app.models.entities import Run, Task
from app.schemas.dto import (
    AllureGenerateOut,
    AllureStatusOut,
    CaseResultOut,
    RunDetailOut,
    RunOut,
)
from app.services import allure_report
from app.services.events import event_hub
from app.services.runner import run_executor

log = get_logger("api.runs")
router = APIRouter(prefix="/api/runs", tags=["runs"])


def _enrich_run(run: Run) -> RunOut:
    out = RunOut.model_validate(run)
    if run.task:
        out.task_name = run.task.name
        out.project_id = run.task.project_id
        if run.task.project:
            out.project_name = run.task.project.name
    return out


@router.get("", response_model=list[RunOut])
async def list_runs(
    project_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[RunOut]:
    stmt = (
        select(Run)
        .options(selectinload(Run.task).selectinload(Task.project))
        .order_by(Run.id.desc())
        .limit(min(limit, 200))
    )
    if project_id is not None:
        stmt = stmt.join(Task).where(Task.project_id == project_id)
    rows = await db.execute(stmt)
    return [_enrich_run(r) for r in rows.scalars().all()]


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> RunDetailOut:
    result = await db.execute(
        select(Run)
        .where(Run.id == run_id)
        .options(
            selectinload(Run.case_results),
            selectinload(Run.task).selectinload(Task.project),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    base = _enrich_run(run)
    return RunDetailOut(
        **base.model_dump(),
        case_results=[CaseResultOut.model_validate(cr) for cr in run.case_results],
        logs=list(getattr(run, "logs", None) or []),
    )


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status in {"passed", "failed", "cancelled"}:
        log.info("cancel ignored run_id=%s already terminal status=%s", run_id, run.status)
        return {"ok": True, "status": run.status}
    log.warning("cancel API run_id=%s from_status=%s", run_id, run.status)
    run_executor.request_cancel(run_id)
    if run.status in {"pending", "running"}:
        run.status = "cancelling"
        await db.commit()
    await event_hub.publish(
        run_id,
        {
            "type": "log",
            "run_id": run_id,
            "level": "info",
            "message": "已请求取消：正在终止运行进程…",
        },
    )
    return {"ok": True, "status": "cancelling"}


@router.get("/{run_id}/allure", response_model=AllureStatusOut)
async def get_allure_status(run_id: int, db: AsyncSession = Depends(get_db)) -> AllureStatusOut:
    result = await db.execute(
        select(Run)
        .where(Run.id == run_id)
        .options(selectinload(Run.case_results))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    return AllureStatusOut(**allure_report.summarize_run(run))


@router.post("/{run_id}/allure/generate", response_model=AllureGenerateOut)
async def generate_allure_report(
    run_id: int, db: AsyncSession = Depends(get_db)
) -> AllureGenerateOut:
    result = await db.execute(
        select(Run)
        .where(Run.id == run_id)
        .options(selectinload(Run.case_results))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")

    log.info("allure generate requested run_id=%s", run_id)
    paths = allure_report.get_report_paths(run_id)
    if not paths["has_results"]:
        try:
            written = allure_report.write_results_for_run(run, list(run.case_results or []))
            run.allure_results_path = written
            await db.commit()
            log.info("run_id=%s wrote missing allure-results → %s", run_id, written)
        except Exception as exc:  # noqa: BLE001
            log.exception("run_id=%s write allure-results failed", run_id)
            raise HTTPException(500, f"写入 allure-results 失败: {exc}") from exc

    try:
        generated = allure_report.generate_html(run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        log.error("run_id=%s allure generate runtime error: %s", run_id, exc)
        raise HTTPException(503, str(exc)) from exc

    run.allure_report_path = generated["report_path"]
    await db.commit()
    return AllureGenerateOut(**generated)


@router.get("/{run_id}/allure/failed-cases")
async def get_allure_failed_cases(run_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        select(Run)
        .where(Run.id == run_id)
        .options(selectinload(Run.case_results))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    summary = allure_report.summarize_run(run)
    return {
        "run_id": run_id,
        "failed_cases": summary["failed_cases"],
        "failed": summary["failed"],
        "total": summary["total"],
    }
