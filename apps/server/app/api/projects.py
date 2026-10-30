"""Project CRUD APIs."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.logging_setup import get_logger
from app.models.entities import Case, Project
from app.schemas.dto import ProjectCreate, ProjectOut, ProjectUpdate

log = get_logger("api.projects")
router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    rows = await db.execute(
        select(Project, func.count(Case.id))
        .outerjoin(Case, Case.project_id == Project.id)
        .group_by(Project.id)
        .order_by(Project.id.desc())
    )
    result: list[ProjectOut] = []
    for project, case_count in rows.all():
        out = ProjectOut.model_validate(project)
        out.case_count = case_count or 0
        result.append(out)
    return result


@router.post("", response_model=ProjectOut)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = Project(**payload.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    log.info("created project_id=%s name=%s", project.id, project.name)
    out = ProjectOut.model_validate(project)
    out.case_count = 0
    return out


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    count = await db.scalar(select(func.count()).select_from(Case).where(Case.project_id == project_id))
    out = ProjectOut.model_validate(project)
    out.case_count = count or 0
    return out


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    count = await db.scalar(select(func.count()).select_from(Case).where(Case.project_id == project_id))
    out = ProjectOut.model_validate(project)
    out.case_count = count or 0
    return out


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await db.delete(project)
    await db.commit()
    log.warning("deleted project_id=%s name=%s", project_id, project.name)
    return {"ok": True}
