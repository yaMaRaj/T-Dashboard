"""Demo data seed and stale-run recovery on API startup."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.logging_setup import get_logger
from app.models.entities import Case, Project, Run
from app.services.compiler import steps_to_python

log = get_logger("seed")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def recover_stale_runs() -> int:
    """Mark orphaned in-flight runs as cancelled after process restart.

    After a restart there is no live worker, so cancelling/running/pending rows
    would otherwise stay stuck forever in the UI.
    """
    fixed = 0
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Run).where(Run.status.in_(["cancelling", "running", "pending"]))
            )
        ).scalars().all()
        for run in rows:
            prev = run.status
            run.status = "cancelled"
            if not run.finished_at:
                run.finished_at = _utc_now()
            if not run.started_at:
                run.started_at = run.finished_at
            if not run.error_summary:
                run.error_summary = (
                    "Cancelled (stale cancelling state recovered on startup)"
                    if prev == "cancelling"
                    else "Interrupted by server restart"
                )
            log.warning("stale run recovered run_id=%s was=%s", run.id, prev)
            fixed += 1
        if fixed:
            await db.commit()
    return fixed

DEMO_PLAYWRIGHT_STEPS = [
    {
        "id": "s1",
        "action": "navigate",
        "name": "打开 Playwright 官网",
        "url": "https://playwright.dev/",
        "selectorType": "css",
    },
    {
        "id": "s2",
        "action": "assert_visible",
        "name": "标题可见",
        "selector": "h1",
        "selectorType": "css",
    },
    {
        "id": "s3",
        "action": "assert_text",
        "name": "标题包含 Playwright",
        "selector": "h1",
        "selectorType": "css",
        "value": "Playwright",
    },
    {
        "id": "s4",
        "action": "click",
        "name": "点击 Get started",
        "selector": "Get started",
        "selectorType": "text",
    },
    {
        "id": "s5",
        "action": "assert_url",
        "name": "进入文档页",
        "value": "intro",
    },
]

# 登录 → 添加商品 → 校验购物车（Sauce Demo）
DEMO_LOGIN_ADD_STEPS = [
    {
        "id": "a1",
        "action": "navigate",
        "name": "打开登录页",
        "url": "https://www.saucedemo.com/",
        "selectorType": "css",
    },
    {
        "id": "a2",
        "action": "fill",
        "name": "输入用户名",
        "selector": "#user-name",
        "selectorType": "css",
        "value": "standard_user",
    },
    {
        "id": "a3",
        "action": "fill",
        "name": "输入密码",
        "selector": "#password",
        "selectorType": "css",
        "value": "secret_sauce",
    },
    {
        "id": "a4",
        "action": "click",
        "name": "点击登录",
        "selector": "#login-button",
        "selectorType": "css",
    },
    {
        "id": "a5",
        "action": "assert_url",
        "name": "已进入库存页",
        "value": "inventory",
    },
    {
        "id": "a6",
        "action": "click",
        "name": "添加背包到购物车",
        "selector": '[data-test="add-to-cart-sauce-labs-backpack"]',
        "selectorType": "css",
    },
    {
        "id": "a7",
        "action": "click",
        "name": "打开购物车",
        "selector": '[data-test="shopping-cart-link"]',
        "selectorType": "css",
    },
    {
        "id": "a8",
        "action": "assert_text",
        "name": "购物车含背包",
        "selector": ".inventory_item_name",
        "selectorType": "css",
        "value": "Sauce Labs Backpack",
    },
]


async def _ensure_project_with_case(
    db,
    *,
    project_name: str,
    description: str,
    base_url: str,
    case_name: str,
    case_description: str,
    tags: list[str],
    steps: list[dict],
) -> None:
    existing = await db.scalar(select(Project).where(Project.name == project_name))
    if existing:
        # Repair demo cases whose steps were wiped (empty array) by a bad save.
        result = await db.execute(select(Case).where(Case.project_id == existing.id))
        for case in result.scalars().all():
            if case.name == case_name and not (case.steps or []):
                case.steps = steps
                case.mode = case.mode or "steps"
                if case.mode == "steps" or not (case.script or "").strip():
                    case.script = steps_to_python(steps, base_url=existing.base_url or base_url)
        return

    project = Project(
        name=project_name,
        description=description,
        base_url=base_url,
        default_browser="chromium",
        default_timeout_ms=30000,
    )
    db.add(project)
    await db.flush()

    db.add(
        Case(
            project_id=project.id,
            name=case_name,
            description=case_description,
            tags=tags,
            enabled=True,
            mode="steps",
            steps=steps,
            script=steps_to_python(steps, base_url=base_url),
        )
    )


async def seed_demo_if_empty() -> None:
    """Ensure built-in demo projects exist (safe to call on every startup)."""
    log.info("ensuring demo projects")
    async with SessionLocal() as db:
        await _ensure_project_with_case(
            db,
            project_name="Demo · Playwright 官网",
            description="内置示例：打开 Playwright 官网并校验文档入口。",
            base_url="https://playwright.dev",
            case_name="官网 Get started 导航",
            case_description="访问官网首页，断言标题，点击 Get started 并校验 URL。",
            tags=["demo", "smoke"],
            steps=DEMO_PLAYWRIGHT_STEPS,
        )
        await _ensure_project_with_case(
            db,
            project_name="Demo · 登录后添加",
            description="内置示例：登录 Sauce Demo，添加商品到购物车并校验。账号 standard_user / secret_sauce。",
            base_url="https://www.saucedemo.com",
            case_name="登录后添加背包到购物车",
            case_description=(
                "使用特定账号登录 → 进入商品页 → 点击添加 → 打开购物车 → 断言商品名称。"
            ),
            tags=["demo", "login", "add"],
            steps=DEMO_LOGIN_ADD_STEPS,
        )
        await db.commit()
