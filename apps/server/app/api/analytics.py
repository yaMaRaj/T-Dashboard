"""Analytics summary: pass rate, failure types, slow cases."""

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.entities import CaseResult, Run, Task
from app.schemas.dto import AnalyticsSummary

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    project_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummary:
    stmt = (
        select(Run)
        .options(selectinload(Run.case_results), selectinload(Run.task))
        .where(Run.status.in_(["passed", "failed", "cancelled"]))
        .order_by(Run.id.desc())
        .limit(100)
    )
    if project_id is not None:
        stmt = stmt.join(Task).where(Task.project_id == project_id)

    rows = await db.execute(stmt)
    runs = list(rows.scalars().all())

    total_runs = len(runs)
    case_results: list[CaseResult] = []
    for run in runs:
        case_results.extend(run.case_results)

    executed = [c for c in case_results if c.status in {"passed", "failed"}]
    total_cases = len(executed)
    passed = sum(1 for c in executed if c.status == "passed")
    pass_rate = (passed / total_cases * 100) if total_cases else 0.0
    avg_duration = (
        sum(c.duration_ms for c in executed) / total_cases if total_cases else 0.0
    )

    # recent pass rates by run (newest first, reverse for chart chronological)
    recent = []
    for run in reversed(runs[:20]):
        total = run.passed + run.failed
        rate = (run.passed / total * 100) if total else 0.0
        recent.append(
            {
                "run_id": run.id,
                "label": f"#{run.id}",
                "pass_rate": round(rate, 1),
                "status": run.status,
            }
        )

    failure_counter: Counter[str] = Counter()
    for c in case_results:
        if c.status == "failed":
            key = c.error_type or "UnknownError"
            failure_counter[key] += 1
    failure_top = [
        {"error_type": k, "count": v} for k, v in failure_counter.most_common(10)
    ]

    # slowest cases by avg duration
    duration_map: dict[str, list[float]] = defaultdict(list)
    for c in executed:
        duration_map[c.case_name].append(c.duration_ms)
    slowest = sorted(
        (
            {
                "case_name": name,
                "avg_duration_ms": sum(vals) / len(vals),
                "samples": len(vals),
            }
            for name, vals in duration_map.items()
        ),
        key=lambda x: x["avg_duration_ms"],
        reverse=True,
    )[:10]

    return AnalyticsSummary(
        total_runs=total_runs,
        total_cases_executed=total_cases,
        pass_rate=round(pass_rate, 1),
        avg_duration_ms=round(avg_duration, 1),
        recent_pass_rates=recent,
        failure_top=failure_top,
        slowest_cases=slowest,
    )
