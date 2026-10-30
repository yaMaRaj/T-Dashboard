"""同步 Playwright 用例执行（仅在 worker 子进程中调用）。

为何用 sync 而不是挂在 uvicorn 上跑：
  Windows 默认 Selector 事件循环无法可靠 spawn Chromium；独立子进程 + sync API 更稳。

模块分工：
  - resolve_vars / locate / run_step_sync：解释执行「步骤」模式的单步
  - _run_user_script：把「脚本」模式写到文件再 subprocess 跑
  - PageChangeCapture：DOM/导航变化时截图
  - _run_steps_case：跑完一个 steps 用例（含录像/失败截图）
  - execute_cases_sync：整次 Run 的用例循环 + 浏览器生命周期
  - finish_keep_alive_browser：有头模式等用户关窗
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Browser, Locator, Page, sync_playwright

from app.config import ARTIFACTS_DIR
from app.logging_setup import get_logger

log = get_logger("step_runner")

# 单个用例「页面变动截图」上限，防止无限 Mutation 打满磁盘
MAX_CHANGE_SHOTS = 40


def _ensure_windows_proactor() -> None:
    """Windows 上把事件循环策略切到 Proactor，否则 Playwright 无法起子进程。

    非 Windows 直接返回。若当前 loop 已关闭则新建 ProactorEventLoop。
    """
    if sys.platform != "win32":
        return
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except Exception:  # noqa: BLE001
        # 没有可用 loop：新建一个
        asyncio.set_event_loop(asyncio.ProactorEventLoop())


def resolve_vars(text: str | None, variables: dict[str, str]) -> str:
    """替换 ``{{key}}`` 占位符；text 为空则返回空串。"""
    if not text:
        return ""
    result = text
    # 逐 key 字面量替换
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def locate(page: Page, step: dict[str, Any], variables: dict[str, str]) -> Locator:
    """按 selectorType 构造 Locator（与 compiler.locate 语义一致，同步版）。"""
    selector = resolve_vars(step.get("selector"), variables)
    selector_type = step.get("selectorType") or "css"
    # role：支持 button[name=登录] 这种编辑器约定
    if selector_type == "role":
        if "[name=" in selector:
            role, _, rest = selector.partition("[name=")
            name = rest.rstrip("]")
            return page.get_by_role(role.strip(), name=name)
        return page.get_by_role(selector)
    if selector_type == "text":
        return page.get_by_text(selector)
    if selector_type == "testid":
        return page.get_by_test_id(selector)
    if selector_type == "placeholder":
        return page.get_by_placeholder(selector)
    if selector_type == "label":
        return page.get_by_label(selector)
    # 默认按 CSS
    return page.locator(selector)


def run_step_sync(
    page: Page,
    step: dict[str, Any],
    *,
    base_url: str = "",
    variables: dict[str, str] | None = None,
    default_timeout_ms: int = 30000,
) -> None:
    """同步执行单个步骤；失败抛 AssertionError / ValueError / NotImplementedError。

    分支顺序：navigate / wait / press / assert_url / custom → 再按 locator 动作分发。
    """
    variables = variables or {}
    timeout = step.get("timeoutMs") or default_timeout_ms
    action = step.get("action")
    page.set_default_timeout(timeout)

    # —— 打开页面：相对路径拼 base_url；load + 尽量 networkidle + 短停顿方便截图 ——
    if action == "navigate":
        url = resolve_vars(step.get("url"), variables)
        if url.startswith("/") and base_url:
            url = base_url.rstrip("/") + url
        page.goto(url, wait_until="load", timeout=timeout)
        try:
            # networkidle 在长轮询站点上可能超时，超时则忽略继续
            page.wait_for_load_state("networkidle", timeout=min(timeout, 8000))
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(400)
        return

    # —— 固定等待 ——
    if action == "wait":
        page.wait_for_timeout(int(step.get("timeoutMs") or 1000))
        return

    # —— 按键：有 selector 则元素上 press，否则全局 keyboard ——
    if action == "press":
        key = resolve_vars(step.get("key"), variables)
        if step.get("selector"):
            locate(page, step, variables).press(key)
        else:
            page.keyboard.press(key)
        return

    # —— URL 包含断言 ——
    if action == "assert_url":
        expected = resolve_vars(step.get("value") or step.get("url"), variables)
        current = page.url
        if expected not in current:
            raise AssertionError(f"URL assertion failed: expected contains '{expected}', got '{current}'")
        return

    # —— 自定义步骤：步骤模式下不执行（请用 script 模式）——
    if action == "custom":
        raise NotImplementedError("Custom code steps are not executed in MVP; use built-in actions.")

    # 以下都需要定位元素
    locator = locate(page, step, variables)

    if action == "click":
        locator.click()
    elif action == "fill":
        locator.fill(resolve_vars(step.get("value"), variables))
    elif action == "select":
        locator.select_option(resolve_vars(step.get("value"), variables))
    elif action == "hover":
        locator.hover()
    elif action == "assert_visible":
        locator.wait_for(state="visible")
    elif action == "assert_text":
        expected = resolve_vars(step.get("value"), variables)
        actual = locator.inner_text()
        if expected not in actual:
            raise AssertionError(f"Text assertion failed: expected contains '{expected}', got '{actual}'")
    elif action == "assert_attribute":
        attr = step.get("attribute") or ""
        expected = resolve_vars(step.get("value"), variables)
        actual = locator.get_attribute(attr)
        # 全等或子串任一满足即可
        if (actual or "") != expected and expected not in (actual or ""):
            raise AssertionError(
                f"Attribute assertion failed: {attr} expected '{expected}', got '{actual}'"
            )
    else:
        raise ValueError(f"Unknown action: {action}")


def _chromium_executable() -> str | None:
    """查找本机 Playwright 安装的完整 Chromium（非 headless-shell）。

    路径：%LOCALAPPDATA%/ms-playwright/chromium-*/chrome-win64/chrome.exe
    取版本号最大的一个；找不到返回 None（交给 Playwright 默认解析）。
    """
    import os

    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not root.exists():
        return None
    matches = sorted(root.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(matches[0]) if matches else None


def _run_user_script(
    *,
    script: str,
    case: dict[str, Any],
    run_id: int,
    on_event,
) -> dict[str, Any]:
    """「脚本」模式：把用户 Python 落到 artifacts 再子进程执行。

    返回结构与 _run_steps_case 对齐（case_id/status/step_results/...），便于上层统一计数。
    退出码 0 → passed；非 0 → failed，并把 stderr/stdout 写入 error_message。
    """
    start = time.perf_counter()
    run_dir = ARTIFACTS_DIR / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    script_path = run_dir / f"case-{case['id']}.py"
    # 落盘后用同一解释器执行，保证依赖与 worker 一致
    script_path.write_text(script, encoding="utf-8")

    on_event(
        {
            "type": "log",
            "run_id": run_id,
            "level": "info",
            "message": f"[{case['name']}] ▶ 执行 Playwright 脚本 ({script_path.name})",
        }
    )

    # 最长 600s，防止脚本死循环占死 worker
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(run_dir),
        timeout=600,
    )
    duration_ms = (time.perf_counter() - start) * 1000
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    # 有 stdout 时推一段到 UI（截断防刷屏）
    if stdout:
        on_event(
            {
                "type": "log",
                "run_id": run_id,
                "level": "info",
                "message": f"[{case['name']}] stdout: {stdout[:2000]}",
            }
        )
    # —— 成功分支 ——
    if completed.returncode == 0:
        return {
            "case_id": case["id"],
            "case_name": case["name"],
            "status": "passed",
            "duration_ms": duration_ms,
            "error_message": "",
            "error_type": "",
            "screenshot_path": "",
            "artifacts": [],
            "step_results": [
                {
                    "index": 0,
                    "name": "Playwright 脚本",
                    "action": "script",
                    "status": "passed",
                    "duration_ms": duration_ms,
                    "error": "",
                }
            ],
        }

    # —— 失败分支：优先 stderr ——
    err = stderr or stdout or f"script exit code {completed.returncode}"
    on_event(
        {
            "type": "log",
            "run_id": run_id,
            "level": "error",
            "message": f"[{case['name']}] ✖ 脚本失败: {err[:2000]}",
        }
    )
    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "status": "failed",
        "duration_ms": duration_ms,
        "error_message": err[:4000],
        "error_type": "ScriptError",
        "screenshot_path": "",
        "artifacts": [],
        "step_results": [
            {
                "index": 0,
                "name": "Playwright 脚本",
                "action": "script",
                "status": "failed",
                "duration_ms": duration_ms,
                "error": err[:2000],
            }
        ],
    }


class PageChangeCapture:
    """监听页面变动并截图（须在 Playwright 同步线程里调用 take/flush）。

    机制：
    1. 注入 MutationObserver → 通过 expose_binding 回调 mark(kind)
    2. 监听 framenavigated / popup → mark
    3. 主流程在每步结束后 flush() → 真正 screenshot
    这样避免在绑定回调里直接截图（易与 goto 竞态）。
    """

    def __init__(
        self,
        page: Page,
        *,
        case_dir: Path,
        rel_prefix: str,
        artifacts: list[dict[str, Any]],
        on_event: Callable[[dict[str, Any]], None],
        run_id: int,
        case_name: str,
        max_shots: int = MAX_CHANGE_SHOTS,
    ) -> None:
        self.page = page
        self.case_dir = case_dir
        # 写入 artifacts 列表时用的相对路径前缀，如 run-1/case-2
        self.rel_prefix = rel_prefix
        self.artifacts = artifacts
        self.on_event = on_event
        self.run_id = run_id
        self.case_name = case_name
        self.max_shots = max_shots
        self._count = 0  # 已截张数
        self._pending_label = "dom"  # 下一次 flush 使用的标签
        self._dirty = False  # True 表示有未落盘的变动
        self._closed = False  # close 后忽略一切 mark/take

    def start(self) -> None:
        """安装 binding、init_script 与导航/弹窗监听。"""
        self.case_dir.mkdir(parents=True, exist_ok=True)

        def _binding(_source: Any, kind: str = "dom") -> None:
            # 只打脏标记，真正截图留给主流程 flush（线程更安全）
            self.mark(str(kind or "dom"))

        # 页面 JS 可调用 window.tdNotifyChange(kind)
        self.page.expose_binding("tdNotifyChange", _binding)
        self.page.add_init_script(
            """
(() => {
  if (window.__tdCaptureInstalled) return;
  window.__tdCaptureInstalled = true;
  let timer = null;
  const notify = (kind) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      try { window.tdNotifyChange(kind); } catch (e) {}
    }, 400);
  };
  const watch = () => {
    if (!document.documentElement) return;
    const obs = new MutationObserver((mutations) => {
      let kind = 'dom';
      for (const m of mutations) {
        const nodes = [...(m.addedNodes || [])];
        for (const n of nodes) {
          if (!(n instanceof Element)) continue;
          const role = (n.getAttribute && n.getAttribute('role')) || '';
          if (
            role === 'dialog' ||
            role === 'alertdialog' ||
            n.getAttribute('aria-modal') === 'true' ||
            /modal|dialog|popup|drawer|overlay/i.test(n.className || '') ||
            /modal|dialog|popup/i.test(n.id || '')
          ) {
            kind = 'dialog';
            break;
          }
        }
        if (kind === 'dialog') break;
      }
      notify(kind);
    });
    obs.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: false,
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else {
    watch();
  }
})();
"""
        )
        # 主 frame 导航 / 弹窗时打脏标记（不在回调里截图）
        self.page.on("framenavigated", self._on_navigated)
        self.page.on("popup", self._on_popup)
        # 故意不挂 dialog handler：忘记 accept/dismiss 会导致页面卡死

    def mark(self, label: str) -> None:
        """记录「有变动待截图」；closed 后忽略。"""
        if self._closed:
            return
        self._pending_label = label
        self._dirty = True

    def flush(self) -> None:
        """若有脏标记则立刻 take 一张；无脏或已关闭则空操作。"""
        if self._closed or not self._dirty:
            return
        self._dirty = False
        self.take(self._pending_label)

    def _on_navigated(self, frame: Any) -> None:
        """仅主 frame 且 http(s) URL 时标记 navigate。"""
        if self._closed:
            return
        try:
            if frame == self.page.main_frame:
                url = (frame.url or "").lower()
                if url.startswith("http://") or url.startswith("https://"):
                    self.mark("navigate")
        except Exception:  # noqa: BLE001
            pass

    def _on_popup(self, popup: Page) -> None:
        """弹窗生命周期不稳定，只 mark，等主流程 flush。"""
        if self._closed:
            return
        self.mark("popup")

    def take(self, label: str) -> None:
        """计数 +1 并调用 _shot_page；达到 max_shots 则不再截。"""
        if self._closed:
            return
        if self._count >= self.max_shots:
            return
        self._count += 1
        self._shot_page(self.page, label, idx=self._count)

    def _shot_page(self, page: Page, label: str, idx: int | None = None) -> None:
        """真正执行 screenshot，并追加到 artifacts + 推 UI 日志。"""
        try:
            # 未传 idx 时自行递增（直接 take 以外的调用路径）
            if idx is None:
                if self._count >= self.max_shots:
                    return
                self._count += 1
                idx = self._count
            url = (page.url or "").lower()
            # about:blank 等非 http 页面跳过，避免空白图
            if not url.startswith("http://") and not url.startswith("https://"):
                return
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(300)
            # 文件名清洗：只留字母数字和 -_
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)[:40]
            filename = f"change-{idx:03d}-{safe}.png"
            path = self.case_dir / filename
            # 视口截图比 full_page 在有头+录像场景更稳
            page.screenshot(path=str(path), full_page=False, animations="disabled")
            rel = f"{self.rel_prefix}/{filename}".replace("\\", "/")
            self.artifacts.append(
                {"type": "screenshot", "path": rel, "label": f"页面变动 · {label}"}
            )
            self.on_event(
                {
                    "type": "log",
                    "run_id": self.run_id,
                    "level": "info",
                    "message": f"[{self.case_name}] 截图 #{idx} ({label})",
                }
            )
        except Exception as exc:  # noqa: BLE001
            # 截图失败不拖垮用例，只记日志
            self.on_event(
                {
                    "type": "log",
                    "run_id": self.run_id,
                    "level": "info",
                    "message": f"[{self.case_name}] 截图跳过: {exc}",
                }
            )

    def close(self) -> None:
        """收尾：先 flush 最后一张，再禁止后续 mark。"""
        self.flush()
        self._closed = True


def _run_steps_case(
    *,
    browser: Browser,
    case: dict[str, Any],
    run_id: int,
    base_url: str,
    timeout_ms: int,
    capture_screenshots: bool,
    record_video: bool,
    headed: bool,
    should_cancel,
    on_event,
) -> dict[str, Any]:
    """执行单个「步骤」模式用例：new_context → 逐步 run_step_sync → 关 context。

    返回 dict：对外字段 + 内部 ``_handoff_url`` / ``_handoff_storage``（供有头接管页复用会话）。
    任一步失败：记 failure.png、status=failed，并 break 不再跑后续步骤。
    取消：抛 InterruptedError → status=skipped。
    """
    # 本用例产物目录：artifacts/run-{id}/case-{id}/
    case_dir = ARTIFACTS_DIR / f"run-{run_id}" / f"case-{case['id']}"
    case_dir.mkdir(parents=True, exist_ok=True)
    rel_prefix = f"run-{run_id}/case-{case['id']}"

    ctx_kwargs: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 720},
    }
    # 开启录像时 Playwright 会把 webm 写到 record_video_dir
    if record_video:
        ctx_kwargs["record_video_dir"] = str(case_dir)
        ctx_kwargs["record_video_size"] = {"width": 1280, "height": 720}

    context = browser.new_context(**ctx_kwargs)
    page = context.new_page()
    video_obj = page.video if record_video else None
    artifacts: list[dict[str, Any]] = []
    capture: PageChangeCapture | None = None

    def _ensure_capture() -> None:
        """懒启动截图监听：未开开关或已启动则跳过。"""
        nonlocal capture
        if not capture_screenshots or capture is not None:
            return
        try:
            capture = PageChangeCapture(
                page,
                case_dir=case_dir,
                rel_prefix=rel_prefix,
                artifacts=artifacts,
                on_event=on_event,
                run_id=run_id,
                case_name=case["name"],
            )
            capture.start()
        except Exception as exc:  # noqa: BLE001
            capture = None
            on_event(
                {
                    "type": "log",
                    "run_id": run_id,
                    "level": "error",
                    "message": f"[{case['name']}] 截图监听启动失败: {exc}",
                }
            )

    step_results: list[dict[str, Any]] = []
    start = time.perf_counter()
    # 步骤里可用 {{baseUrl}}
    variables = {"baseUrl": base_url}
    status = "passed"
    error_message = ""
    error_type = ""
    screenshot_rel = ""

    try:
        # —— 逐步执行 ——
        for index, step in enumerate(case.get("steps") or []):
            # 每步前检查取消文件
            if should_cancel():
                raise InterruptedError("Cancelled")
            step_start = time.perf_counter()
            step_name = step.get("name") or step.get("action") or f"step-{index + 1}"
            on_event(
                {
                    "type": "log",
                    "run_id": run_id,
                    "level": "info",
                    "message": f"[{case['name']}] ▶ {step_name}",
                }
            )
            try:
                action = step.get("action")
                # 真正执行动作
                run_step_sync(
                    page,
                    step,
                    base_url=base_url,
                    variables=variables,
                    default_timeout_ms=timeout_ms,
                )
                # 首次 navigate 后再装截图监听，避免与 goto 竞态
                if action == "navigate":
                    _ensure_capture()
                    if capture is not None:
                        capture.mark("navigate")
                elif capture is None:
                    _ensure_capture()

                # 本步结束：把积压的 DOM 变动截下来
                if capture is not None:
                    capture.flush()
                step_results.append(
                    {
                        "index": index,
                        "name": step_name,
                        "action": step.get("action"),
                        "status": "passed",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "error": "",
                    }
                )
            except Exception as step_exc:  # noqa: BLE001
                # 步骤失败：尽量截图，记录错误，跳出 for（不再跑后续步）
                _ensure_capture()
                if capture is not None:
                    capture.flush()
                step_results.append(
                    {
                        "index": index,
                        "name": step_name,
                        "action": step.get("action"),
                        "status": "failed",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "error": str(step_exc),
                    }
                )
                status = "failed"
                error_message = str(step_exc)
                error_type = type(step_exc).__name__
                try:
                    fail_name = "failure.png"
                    fail_path = case_dir / fail_name
                    page.wait_for_timeout(300)
                    page.screenshot(
                        path=str(fail_path),
                        full_page=False,
                        animations="disabled",
                    )
                    screenshot_rel = f"{rel_prefix}/{fail_name}"
                    artifacts.append(
                        {
                            "type": "screenshot",
                            "path": screenshot_rel,
                            "label": "失败截图",
                        }
                    )
                except Exception:  # noqa: BLE001
                    screenshot_rel = ""
                on_event(
                    {
                        "type": "log",
                        "run_id": run_id,
                        "level": "error",
                        "message": f"[{case['name']}] ✖ {step_name}: {step_exc}",
                    }
                )
                break
    except InterruptedError:
        # 用户取消：整用例算 skipped
        status = "skipped"
        error_message = "Cancelled"
    finally:
        # 关自动化 context 前快照 URL/storage，供 keep-alive 接管页复用登录态
        handoff_url = ""
        handoff_storage: dict[str, Any] | None = None
        try:
            handoff_url = page.url or ""
            handoff_storage = context.storage_state()
        except Exception:  # noqa: BLE001
            pass

        if capture is not None:
            capture.close()
        try:
            # close context 会结束录像文件写入
            context.close()
        except Exception:  # noqa: BLE001
            pass

        # 收集 webm：优先 video.path()，否则扫目录
        if record_video:
            video_files: list[Path] = []
            if video_obj is not None:
                try:
                    hinted = video_obj.path()
                    if hinted and Path(hinted).exists():
                        video_files = [Path(hinted)]
                except Exception:  # noqa: BLE001
                    pass
            if not video_files:
                video_files = sorted(case_dir.glob("*.webm"))
            for video in video_files:
                try:
                    # 若文件不在 case_dir，复制进来再登记相对路径
                    if video.parent.resolve() != case_dir.resolve():
                        target = case_dir / video.name
                        if not target.exists():
                            target.write_bytes(video.read_bytes())
                        video = target
                    rel = f"{rel_prefix}/{video.name}".replace("\\", "/")
                except Exception:  # noqa: BLE001
                    rel = f"{rel_prefix}/{video.name}".replace("\\", "/")
                artifacts.append({"type": "video", "path": rel, "label": "全程录像"})
                on_event(
                    {
                        "type": "log",
                        "run_id": run_id,
                        "level": "info",
                        "message": f"[{case['name']}] 录像已保存: {video.name}",
                    }
                )

    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "status": status,
        "duration_ms": (time.perf_counter() - start) * 1000,
        "error_message": error_message,
        "error_type": error_type,
        "screenshot_path": screenshot_rel,
        "artifacts": artifacts,
        "step_results": step_results,
        # 以下以下划线开头：上层 execute 会剥离，不写进 DB
        "_handoff_url": handoff_url,
        "_handoff_storage": handoff_storage,
    }


def _wait_until_browser_closed(browser: Browser, *, should_cancel, on_event, run_id: int) -> None:
    """阻塞直到浏览器断开连接，或 should_cancel 为真时主动 close。"""
    on_event(
        {
            "type": "log",
            "run_id": run_id,
            "level": "info",
            "message": "自动化已结束。浏览器保持打开，可继续手动操作；关闭浏览器窗口后任务进程才会退出。",
        }
    )
    try:
        while browser.is_connected():
            if should_cancel():
                on_event(
                    {
                        "type": "log",
                        "run_id": run_id,
                        "level": "info",
                        "message": "收到取消：关闭保持中的浏览器…",
                    }
                )
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
                break
            time.sleep(0.5)
    except Exception:  # noqa: BLE001
        pass


def execute_cases_sync(
    *,
    browser_name: str,
    headless: bool,
    timeout_ms: int,
    base_url: str,
    cases: list[dict[str, Any]],
    run_id: int,
    should_cancel,
    on_event,
    capture_screenshots: bool = False,
    record_video: bool = False,
    keep_browser_open: bool = False,
) -> dict[str, Any]:
    """跑完本 Run 的全部用例，返回汇总 outcome。

    流程：
    1. 判断是否需要浏览器（存在 steps 模式用例）
    2. launch → for case：script 或 steps → 累计 passed/failed/skipped
    3. keep_open 时开接管页并挂到模块级 _KEEP_ALIVE；否则关掉 browser/pw
    """
    _ensure_windows_proactor()
    passed = failed = skipped = 0
    case_payloads: list[dict[str, Any]] = []
    run_start = time.perf_counter()
    error_summary = ""
    last_handoff_url = ""
    last_handoff_storage: dict[str, Any] | None = None

    # 纯 script 用例不强制起浏览器；有 steps 才需要
    step_cases = [c for c in cases if (c.get("mode") or "steps") != "script"]
    needs_browser = bool(step_cases)
    # 截图/录像也强制 headed（否则拿不到有意义画面）
    use_headed = ((not headless) or capture_screenshots or record_video) and needs_browser
    keep_open = bool(keep_browser_open and use_headed)
    log.info(
        "run_id=%s execute cases=%s needs_browser=%s headed=%s keep_open=%s browser=%s",
        run_id,
        len(cases),
        needs_browser,
        use_headed,
        keep_open,
        browser_name,
    )

    browser = None
    pw = None
    handoff_context = None

    try:
        # —— 启动浏览器（仅当有步骤用例）——
        if needs_browser:
            pw = sync_playwright().start()
            # 非法 browser_name 时回退 chromium
            browser_type = getattr(pw, browser_name, pw.chromium)
            launch_kwargs: dict[str, Any] = {
                "headless": not use_headed,
                "args": [
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            }
            if use_headed:
                # 放慢操作，便于肉眼观察
                launch_kwargs["slow_mo"] = 250
            exe = _chromium_executable() if browser_name == "chromium" else None
            if exe:
                launch_kwargs["executable_path"] = exe
                log.debug("run_id=%s chromium exe=%s", run_id, exe)
            browser = browser_type.launch(**launch_kwargs)
            log.info("run_id=%s browser launched headed=%s", run_id, use_headed)
            on_event(
                {
                    "type": "log",
                    "run_id": run_id,
                    "level": "info",
                    "message": (
                        "浏览器模式: 可视窗口 (headed)"
                        if use_headed
                        else "浏览器模式: 无头 (headless)"
                    ),
                }
            )

        # —— 用例循环 ——
        for case in cases:
            if should_cancel():
                # 取消：当前用例记 skipped 并中断后续用例
                log.warning("run_id=%s cancel flag seen before case_id=%s", run_id, case.get("id"))
                skipped += 1
                case_payloads.append(
                    {
                        "case_id": case["id"],
                        "case_name": case["name"],
                        "status": "skipped",
                        "duration_ms": 0,
                        "error_message": "Cancelled",
                        "error_type": "",
                        "screenshot_path": "",
                        "artifacts": [],
                        "step_results": [],
                    }
                )
                break

            log.info(
                "run_id=%s case_start id=%s name=%s mode=%s",
                run_id,
                case.get("id"),
                case.get("name"),
                case.get("mode") or "steps",
            )
            on_event(
                {
                    "type": "case_started",
                    "run_id": run_id,
                    "case_id": case["id"],
                    "case_name": case["name"],
                }
            )

            mode = case.get("mode") or "steps"
            # 分支：脚本模式 vs 步骤模式
            if mode == "script" and (case.get("script") or "").strip():
                payload = _run_user_script(
                    script=case["script"],
                    case=case,
                    run_id=run_id,
                    on_event=on_event,
                )
            else:
                assert browser is not None
                payload = _run_steps_case(
                    browser=browser,
                    case=case,
                    run_id=run_id,
                    base_url=base_url,
                    timeout_ms=timeout_ms,
                    capture_screenshots=capture_screenshots,
                    record_video=record_video,
                    headed=use_headed,
                    should_cancel=should_cancel,
                    on_event=on_event,
                )
                # 记住最后一次会话，给接管页用
                if payload.get("_handoff_url"):
                    last_handoff_url = payload["_handoff_url"]
                if payload.get("_handoff_storage") is not None:
                    last_handoff_storage = payload["_handoff_storage"]

            # 去掉内部字段再入列表（避免写进 CaseResult JSON）
            public_payload = {
                k: v for k, v in payload.items() if not str(k).startswith("_")
            }
            case_payloads.append(public_payload)
            if public_payload["status"] == "passed":
                passed += 1
            elif public_payload["status"] == "failed":
                failed += 1
            else:
                skipped += 1
            log.info(
                "run_id=%s case_done id=%s status=%s duration_ms=%s err=%s",
                run_id,
                case.get("id"),
                public_payload["status"],
                public_payload["duration_ms"],
                (public_payload.get("error_message") or "")[:200],
            )
            on_event(
                {
                    "type": "case_finished",
                    "run_id": run_id,
                    "case_id": case["id"],
                    "case_name": case["name"],
                    "status": public_payload["status"],
                    "duration_ms": public_payload["duration_ms"],
                    "error_message": public_payload["error_message"],
                }
            )

        # —— 有头 keep-alive：新开无录像的 context，打开最后 URL 供人工操作 ——
        if keep_open and browser is not None and browser.is_connected():
            try:
                ctx_kwargs: dict[str, Any] = {
                    "viewport": {"width": 1280, "height": 720},
                }
                if last_handoff_storage is not None:
                    ctx_kwargs["storage_state"] = last_handoff_storage
                handoff_context = browser.new_context(**ctx_kwargs)
                handoff_page = handoff_context.new_page()
                target = last_handoff_url or base_url or "about:blank"
                if target and target != "about:blank":
                    try:
                        handoff_page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    except Exception:  # noqa: BLE001
                        pass
                on_event(
                    {
                        "type": "log",
                        "run_id": run_id,
                        "level": "info",
                        "message": f"已进入手动接管页: {handoff_page.url}",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                on_event(
                    {
                        "type": "log",
                        "run_id": run_id,
                        "level": "error",
                        "message": f"保持浏览器打开失败: {exc}",
                    }
                )
                keep_open = False

    except Exception as exc:  # noqa: BLE001
        # 顶层崩溃：写入 error_summary，并禁止 keep_open
        error_summary = str(exc)
        keep_open = False
        log.exception("run_id=%s execute_cases_sync fatal: %s", run_id, exc)

    # —— 组装返回给 worker 的 outcome ——
    outcome = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_ms": (time.perf_counter() - run_start) * 1000,
        "error_summary": error_summary,
        "case_payloads": case_payloads,
        "cancelled": should_cancel(),
        "keep_browser_open": keep_open,
    }
    log.info(
        "run_id=%s outcome passed=%s failed=%s skipped=%s cancelled=%s duration_ms=%.0f",
        run_id,
        passed,
        failed,
        skipped,
        outcome["cancelled"],
        outcome["duration_ms"],
    )

    # keep_open：把活对象挂到模块全局，等 worker 调 finish_keep_alive_browser
    # 否则立刻关闭 browser / 停止 playwright
    global _KEEP_ALIVE  # noqa: PLW0603
    if keep_open and browser is not None:
        _KEEP_ALIVE = {
            "browser": browser,
            "pw": pw,
            "context": handoff_context,
            "should_cancel": should_cancel,
            "on_event": on_event,
            "run_id": run_id,
        }
    else:
        _KEEP_ALIVE = None
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:  # noqa: BLE001
                pass

    return outcome


# 有头 keep-alive 会话暂存（单 worker 同时只跑一个 Run，故用模块全局足够）
_KEEP_ALIVE: dict[str, Any] | None = None


def finish_keep_alive_browser() -> None:
    """worker 在写完 result.json 后调用：阻塞等到用户关窗，再 stop Playwright。

    步骤：取出并清空 _KEEP_ALIVE → 等待关窗/取消 → finally 里关 context/browser/pw。
    """
    global _KEEP_ALIVE  # noqa: PLW0603
    session = _KEEP_ALIVE
    # 先清空，避免重复 finish
    _KEEP_ALIVE = None
    if not session:
        return
    browser = session["browser"]
    try:
        # 阻塞循环：用户关窗或 cancel 文件出现才返回
        _wait_until_browser_closed(
            browser,
            should_cancel=session["should_cancel"],
            on_event=session["on_event"],
            run_id=session["run_id"],
        )
    finally:
        # 无论正常返回还是异常，都释放 Playwright 资源
        try:
            if session.get("context") is not None:
                session["context"].close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if browser.is_connected():
                browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if session.get("pw") is not None:
                session["pw"].stop()
        except Exception:  # noqa: BLE001
            pass
