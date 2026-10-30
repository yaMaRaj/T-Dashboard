"""Case CRUD, code export, and steps→script generation."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.logging_setup import get_logger
from app.models.entities import Case, Project
from app.schemas.dto import CaseCreate, CaseOut, CaseUpdate
from app.services.compiler import steps_to_python

log = get_logger("api.cases")
router = APIRouter(tags=["cases"])


@router.get("/api/projects/{project_id}/cases", response_model=list[CaseOut])
async def list_cases(project_id: int, db: AsyncSession = Depends(get_db)) -> list[Case]:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rows = await db.execute(
        select(Case).where(Case.project_id == project_id).order_by(Case.id.desc())
    )
    return list(rows.scalars().all())


@router.post("/api/projects/{project_id}/cases", response_model=CaseOut)
async def create_case(
    project_id: int, payload: CaseCreate, db: AsyncSession = Depends(get_db)
) -> Case:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    steps = [s.model_dump() for s in payload.steps]
    script = payload.script or steps_to_python(steps, base_url=project.base_url)
    case = Case(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
        enabled=payload.enabled,
        mode=payload.mode or "steps",
        steps=steps,
        script=script,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    log.info(
        "created case_id=%s project_id=%s name=%s mode=%s steps=%s",
        case.id,
        project_id,
        case.name,
        case.mode,
        len(steps),
    )
    return case


@router.get("/api/cases/{case_id}", response_model=CaseOut)
async def get_case(case_id: int, db: AsyncSession = Depends(get_db)) -> Case:
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@router.patch("/api/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: int, payload: CaseUpdate, db: AsyncSession = Depends(get_db)
) -> Case:
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    data = payload.model_dump(exclude_unset=True)
    if "steps" in data and payload.steps is not None:
        new_steps = [s.model_dump() for s in payload.steps]
        # Guard: ignore empty steps wipe unless this is an explicit steps-mode save
        # (script/meta saves used to send steps:[] from a stale empty editor).
        if len(new_steps) == 0 and (case.steps or []) and data.get("mode") != "steps":
            log.warning(
                "case_id=%s ignored empty steps wipe (mode=%s existing_steps=%s)",
                case_id,
                data.get("mode"),
                len(case.steps or []),
            )
            data.pop("steps", None)
        else:
            data["steps"] = new_steps
    for key, value in data.items():
        setattr(case, key, value)

    # When saving steps mode without explicit script, keep script in sync.
    if case.mode == "steps" and "script" not in data:
        project = await db.get(Project, case.project_id)
        case.script = steps_to_python(
            case.steps or [],
            base_url=project.base_url if project else "",
        )

    await db.commit()
    await db.refresh(case)
    log.info("updated case_id=%s fields=%s", case_id, list(data.keys()))
    return case


@router.delete("/api/cases/{case_id}")
async def delete_case(case_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    await db.delete(case)
    await db.commit()
    log.warning("deleted case_id=%s name=%s", case_id, case.name)
    return {"ok": True}


@router.get("/api/cases/{case_id}/code")
async def export_case_code(case_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    project = await db.get(Project, case.project_id)
    generated = steps_to_python(
        case.steps or [],
        base_url=project.base_url if project else "",
    )
    # Prefer stored script when in script mode or when script has content
    code = case.script if (case.mode == "script" and case.script) else (case.script or generated)
    return {
        "language": "python",
        "mode": case.mode or "steps",
        "code": code,
        "generated": generated,
    }


@router.post("/api/cases/{case_id}/generate-script", response_model=CaseOut)
async def generate_script_from_steps(
    case_id: int, db: AsyncSession = Depends(get_db)
) -> Case:
    """Overwrite case.script from current steps (does not change mode)."""
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    project = await db.get(Project, case.project_id)
    case.script = steps_to_python(
        case.steps or [],
        base_url=project.base_url if project else "",
    )
    await db.commit()
    await db.refresh(case)
    return case
