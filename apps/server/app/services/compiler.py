"""步骤编译与（历史）异步单步执行辅助。

主要职责：
1. resolve_vars / locate / run_step —— 在异步 Playwright Page 上解释执行单步（较少直接用到）。
2. locator_expr / steps_to_python —— 把可视化步骤 JSON 编译成可复制的 sync Playwright Python 脚本，
   供用例「脚本」页展示与导出。真正跑测由 step_runner_sync 在子进程里执行，不走本文件的 run_step。
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page


def resolve_vars(text: str | None, variables: dict[str, str]) -> str:
    """把模板字符串里的 ``{{key}}`` 替换成 variables[key]。

    例如 text=\"Hello {{user}}\"、variables={\"user\":\"Ada\"} → \"Hello Ada\"。
    """
    # 空值直接返回空串，避免后续 replace 对 None 报错
    if not text:
        return ""
    result = text
    # 逐个变量做字面量替换（不做正则，避免特殊字符干扰）
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def locate(page: Page, step: dict[str, Any], variables: dict[str, str]) -> Locator:
    """根据步骤里的 selectorType + selector，在 page 上构造 Playwright Locator。

    分支含义：
    - role：无障碍角色；若 selector 形如 ``button[name=登录]`` 则拆成 role + accessible name
    - text / testid / placeholder / label：对应 Playwright 的 get_by_* API
    - 默认 css：page.locator(css)
    """
    # 先对选择器做变量替换，再按类型分发
    selector = resolve_vars(step.get("selector"), variables)
    selector_type = step.get("selectorType") or "css"

    if selector_type == "role":
        # 约定格式 role[name=可见名]，便于可视化编辑器录入
        if "[name=" in selector:
            role, _, rest = selector.partition("[name=")
            name = rest.rstrip("]")
            return page.get_by_role(role.strip(), name=name)
        # 只有角色名时，不带 name 过滤
        return page.get_by_role(selector)

    if selector_type == "text":
        return page.get_by_text(selector)

    if selector_type == "testid":
        return page.get_by_test_id(selector)

    if selector_type == "placeholder":
        return page.get_by_placeholder(selector)

    if selector_type == "label":
        return page.get_by_label(selector)

    # 未识别的类型一律当 CSS 选择器
    return page.locator(selector)


async def run_step(
    page: Page,
    step: dict[str, Any],
    *,
    base_url: str = "",
    variables: dict[str, str] | None = None,
    default_timeout_ms: int = 30000,
) -> None:
    """在异步 Page 上执行单个步骤字典。

    流程：解析超时与 action → 按 action 分支调用 Playwright → 断言失败则抛 AssertionError。
    注意：生产执行路径用的是 sync 版 step_runner_sync.run_step_sync，本函数主要用于兼容/实验。
    """
    variables = variables or {}
    # 步骤级超时优先，否则用默认
    timeout = step.get("timeoutMs") or default_timeout_ms
    action = step.get("action")
    page.set_default_timeout(timeout)

    # —— 导航：打开 URL；相对路径则拼上项目 base_url ——
    if action == "navigate":
        url = resolve_vars(step.get("url"), variables)
        if url.startswith("/") and base_url:
            url = base_url.rstrip("/") + url
        await page.goto(url, wait_until="domcontentloaded")
        return

    # —— 纯等待：固定 sleep 毫秒 ——
    if action == "wait":
        await page.wait_for_timeout(int(step.get("timeoutMs") or 1000))
        return

    # —— 按键：有选择器则在元素上 press，否则全局 keyboard ——
    if action == "press":
        key = resolve_vars(step.get("key"), variables)
        selector = step.get("selector")
        if selector:
            await locate(page, step, variables).press(key)
        else:
            await page.keyboard.press(key)
        return

    # —— URL 断言：当前 URL 须包含期望子串 ——
    if action == "assert_url":
        expected = resolve_vars(step.get("value") or step.get("url"), variables)
        current = page.url
        if expected not in current:
            raise AssertionError(f"URL assertion failed: expected contains '{expected}', got '{current}'")
        return

    # —— 自定义代码：MVP 不在异步路径执行 ——
    if action == "custom":
        raise NotImplementedError("Custom code steps are not executed in MVP; use built-in actions.")

    # 以下动作都依赖定位器，先统一构造
    locator = locate(page, step, variables)

    if action == "click":
        await locator.click()
    elif action == "fill":
        # 输入框填值（同样支持 {{var}}）
        await locator.fill(resolve_vars(step.get("value"), variables))
    elif action == "select":
        await locator.select_option(resolve_vars(step.get("value"), variables))
    elif action == "hover":
        await locator.hover()
    elif action == "assert_visible":
        await locator.wait_for(state="visible")
    elif action == "assert_text":
        expected = resolve_vars(step.get("value"), variables)
        actual = await locator.inner_text()
        # 使用「包含」而非全等，兼容前后空白/多余文案
        if expected not in actual:
            raise AssertionError(f"Text assertion failed: expected contains '{expected}', got '{actual}'")
    elif action == "assert_attribute":
        attr = step.get("attribute") or ""
        expected = resolve_vars(step.get("value"), variables)
        actual = await locator.get_attribute(attr)
        # 允许全等或子串匹配
        if (actual or "") != expected and expected not in (actual or ""):
            raise AssertionError(
                f"Attribute assertion failed: {attr} expected '{expected}', got '{actual}'"
            )
    else:
        # 未知动作直接失败，避免静默跳过
        raise ValueError(f"Unknown action: {action}")


def _py_str(value: str | None) -> str:
    """把字符串变成合法 Python 字面量（带引号、转义），用于代码生成。"""
    return repr(value or "")


def locator_expr(step: dict[str, Any]) -> str:
    """生成「定位器」的 Python 源码片段，例如 ``page.get_by_text('登录')``。

    逻辑与 locate() 对称，但返回的是字符串而不是 Locator 对象，供 steps_to_python 拼脚本。
    """
    selector = step.get("selector") or ""
    selector_type = step.get("selectorType") or "css"

    if selector_type == "text":
        return f"page.get_by_text({_py_str(selector)})"
    if selector_type == "testid":
        return f"page.get_by_test_id({_py_str(selector)})"
    if selector_type == "placeholder":
        return f"page.get_by_placeholder({_py_str(selector)})"
    if selector_type == "label":
        return f"page.get_by_label({_py_str(selector)})"
    if selector_type == "role":
        # 与 locate 相同：解析 role[name=...]
        if "[name=" in selector:
            role, _, rest = selector.partition("[name=")
            name = rest.rstrip("]")
            return f"page.get_by_role({_py_str(role.strip())}, name={_py_str(name)})"
        return f"page.get_by_role({_py_str(selector)})"
    # 默认 CSS
    return f"page.locator({_py_str(selector)})"


def steps_to_python(
    steps: list[dict[str, Any]],
    *,
    base_url: str = "",
    browser: str = "chromium",
    headless: bool = True,
) -> str:
    """把步骤列表编译成一份可独立运行的 sync Playwright 脚本字符串。

    生成结构：
    1. import + 本地 Chromium 查找函数（Windows ms-playwright 目录）
    2. with sync_playwright() 启动浏览器、new_page
    3. for 每个 step：按 action 追加一行或多行调用
    4. browser.close()

    相对 URL（以 / 开头）会拼上 base_url。不支持的 action 写成 TODO 注释。
    """
    # —— 脚本固定头部：依赖与启动浏览器 ——
    lines = [
        "import os",
        "from pathlib import Path",
        "from playwright.sync_api import sync_playwright",
        "",
        "def _chromium_exe():",
        '    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"',
        '    matches = sorted(root.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)',
        "    return str(matches[0]) if matches else None",
        "",
        "with sync_playwright() as p:",
        "    launch_kwargs = {" + f"'headless': {headless!r}" + "}",
        "    if " + f"{browser!r}" + " == 'chromium':",
        "        exe = _chromium_exe()",
        "        if exe:",
        "            launch_kwargs = {",
        "                'executable_path': exe,",
        "                'headless': False,",
        "                'args': ['--headless=new', '--disable-gpu'],",
        "            }",
        f"    browser = p.{browser}.launch(**launch_kwargs)",
        "    page = browser.new_page()",
    ]

    # —— 循环：把每一步翻译成缩进在 with 块内的语句 ——
    for step in steps:
        action = step.get("action")
        name = step.get("name") or action
        # 注释行方便人读生成脚本
        lines.append(f"    # {name}")

        if action == "navigate":
            url = step.get("url") or ""
            # 相对路径 → 绝对 URL
            if url.startswith("/") and base_url:
                url = base_url.rstrip("/") + url
            lines.append(f"    page.goto({_py_str(url)})")

        elif action == "click":
            lines.append(f"    {locator_expr(step)}.click()")

        elif action == "fill":
            lines.append(f"    {locator_expr(step)}.fill({_py_str(step.get('value'))})")

        elif action == "select":
            lines.append(f"    {locator_expr(step)}.select_option({_py_str(step.get('value'))})")

        elif action == "hover":
            lines.append(f"    {locator_expr(step)}.hover()")

        elif action == "press":
            key = step.get("key") or "Enter"
            # 有 selector：在元素上按键；否则全局 keyboard
            if step.get("selector"):
                lines.append(f"    {locator_expr(step)}.press({_py_str(key)})")
            else:
                lines.append(f"    page.keyboard.press({_py_str(key)})")

        elif action == "wait":
            lines.append(f"    page.wait_for_timeout({int(step.get('timeoutMs') or 1000)})")

        elif action == "assert_visible":
            lines.append(f"    {locator_expr(step)}.wait_for(state='visible')")

        elif action == "assert_text":
            lines.append(f"    assert {_py_str(step.get('value'))} in {locator_expr(step)}.inner_text()")

        elif action == "assert_url":
            expected = step.get("value") or step.get("url") or ""
            lines.append(f"    assert {_py_str(expected)} in page.url")

        elif action == "assert_attribute":
            attr = step.get("attribute") or ""
            lines.append(
                f"    assert {_py_str(step.get('value'))} in ({locator_expr(step)}.get_attribute({_py_str(attr)}) or '')"
            )

        elif action == "custom" and step.get("code"):
            # 自定义代码按行原样缩进嵌入（信任编辑器内容）
            for raw in (step.get("code") or "").splitlines():
                lines.append(f"    {raw}")

        else:
            # 未知动作：不生成可执行语句，只留 TODO，避免生成错误脚本
            lines.append(f"    # TODO: unsupported action {action!r}")

    # —— 收尾：关浏览器，并用换行拼成完整源码 ——
    lines.extend(["    browser.close()", ""])
    return "\n".join(lines)
