/**
 * 与后端通信的唯一 HTTP 封装。
 *
 * 开发时 Vite 把 /api、/artifacts、/ws 代理到 FastAPI（见 vite.config.ts）。
 * 所有业务视图应通过本文件的 `api.*` 方法访问后端，不要散落 fetch。
 */

import type {
  AllureGenerateResult,
  AllureStatus,
  AnalyticsSummary,
  Case,
  Project,
  Run,
  Step,
  Task,
} from '@/types'
import { createLogger } from '@/utils/logger'

const log = createLogger('api')

/**
 * 通用请求：JSON body、统一错误抛出。
 * - 非 2xx：读文本作为 Error.message 抛出（后端 detail 常在此）
 * - 204：返回 undefined
 * - 其它：res.json()
 */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const method = init?.method || 'GET'
  log.debug(`${method} ${url}`)
  const started = performance.now()
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      ...init,
    })
    const ms = Math.round(performance.now() - started)
    // 失败：打 error 日志并抛出，交给调用方 catch 展示 UI
    if (!res.ok) {
      const text = await res.text()
      log.error(`${method} ${url} → ${res.status} (${ms}ms)`, text.slice(0, 500))
      throw new Error(text || res.statusText)
    }
    log.debug(`${method} ${url} → ${res.status} (${ms}ms)`)
    if (res.status === 204) return undefined as T
    return res.json() as Promise<T>
  } catch (err) {
    // 网络层失败（断网等）：若还不是我们抛过的 Error，补一条日志
    if (!(err instanceof Error && err.message)) {
      log.error(`${method} ${url} network/error`, err)
    }
    throw err
  }
}

/** 按资源分组的 API 方法表。 */
export const api = {
  // —— 健康与环境 ——
  health: () => request<{ status: string }>('/api/health'),
  playwrightStatus: () =>
    request<{ installed: boolean; message: string; hint?: string }>('/api/playwright/status'),

  // —— 项目 ——
  listProjects: () => request<Project[]>('/api/projects'),
  createProject: (body: Partial<Project> & { name: string }) =>
    request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  updateProject: (id: number, body: Partial<Project>) =>
    request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: number) => request<{ ok: boolean }>(`/api/projects/${id}`, { method: 'DELETE' }),

  // —— 用例 ——
  listCases: (projectId: number) => request<Case[]>(`/api/projects/${projectId}/cases`),
  createCase: (projectId: number, body: { name: string; description?: string; tags?: string[]; steps?: Step[] }) =>
    request<Case>(`/api/projects/${projectId}/cases`, { method: 'POST', body: JSON.stringify(body) }),
  getCase: (id: number) => request<Case>(`/api/cases/${id}`),
  updateCase: (id: number, body: Partial<Case>) =>
    request<Case>(`/api/cases/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteCase: (id: number) => request<{ ok: boolean }>(`/api/cases/${id}`, { method: 'DELETE' }),
  exportCaseCode: (id: number) =>
    request<{ language: string; mode: string; code: string; generated: string }>(`/api/cases/${id}/code`),
  generateScript: (id: number) =>
    request<Case>(`/api/cases/${id}/generate-script`, { method: 'POST' }),

  // —— 任务 / 触发运行 ——
  createTask: (
    projectId: number,
    body: {
      name: string
      case_ids: number[]
      browser?: string
      headless?: boolean
      timeout_ms?: number
      capture_screenshots?: boolean
      record_video?: boolean
      run_immediately?: boolean
    },
  ) =>
    request<{ task: Task; run: Run | null }>(`/api/projects/${projectId}/tasks`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // —— 运行记录与 Allure ——
  listRuns: (projectId?: number) =>
    request<Run[]>(projectId ? `/api/runs?project_id=${projectId}` : '/api/runs'),
  getRun: (id: number) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: number) => request<{ ok: boolean }>(`/api/runs/${id}/cancel`, { method: 'POST' }),
  getAllureStatus: (id: number) => request<AllureStatus>(`/api/runs/${id}/allure`),
  generateAllureReport: (id: number) =>
    request<AllureGenerateResult>(`/api/runs/${id}/allure/generate`, { method: 'POST' }),

  // —— 分析 ——
  analytics: (projectId?: number) =>
    request<AnalyticsSummary>(
      projectId ? `/api/analytics/summary?project_id=${projectId}` : '/api/analytics/summary',
    ),
}
