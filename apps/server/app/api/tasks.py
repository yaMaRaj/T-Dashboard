"""Task CRUD and enqueue endpoints (create task → optional immediate run)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.logging_setup import get_logger
from app.models.entities import Project, Run, Task
from app.schemas.dto import RunOut, TaskCreate, TaskOut
from app.services.queue import job_queue

log = get_logger("api.tasks")
router = APIRouter(tags=["tasks"])


@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(project_id: int, db: AsyncSession = Depends(get_db)) -> list[Task]:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rows = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.id.desc())
    )
    return list(rows.scalars().all())


@router.post("/api/projects/{project_id}/tasks", response_model=dict)
async def create_task(
    project_id: int, payload: TaskCreate, db: AsyncSession = Depends(get_db)
) -> dict:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    task = Task(
        project_id=project_id,
        name=payload.name,
        case_ids=payload.case_ids,
        browser=payload.browser,
        headless=payload.headless,
        retries=payload.retries,
        timeout_ms=payload.timeout_ms,
        capture_screenshots=payload.capture_screenshots,
        record_video=payload.record_video,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    log.info(
        "created task_id=%s project_id=%s name=%s case_ids=%s run_immediately=%s",
        task.id,
        project_id,
        task.name,
        payload.case_ids,
        payload.run_immediately,
    )

    run_out = None
    if payload.run_immediately:
        run = Run(task_id=task.id, status="pending", total=len(payload.case_ids))
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await job_queue.enqueue(run.id)
        log.info("created run_id=%s for task_id=%s", run.id, task.id)
        run_out = RunOut.model_validate(run)

    return {
        "task": TaskOut.model_validate(task),
        "run": run_out,
    }


@router.post("/api/tasks/{task_id}/run", response_model=RunOut)
async def run_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Run:
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    run = Run(task_id=task.id, status="pending", total=len(task.case_ids or []))
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await job_queue.enqueue(run.id)
    log.info("re-run task_id=%s → run_id=%s", task_id, run.id)
    return run
