export type StepAction =
  | 'navigate'
  | 'click'
  | 'fill'
  | 'select'
  | 'hover'
  | 'press'
  | 'wait'
  | 'assert_visible'
  | 'assert_text'
  | 'assert_url'
  | 'assert_attribute'
  | 'custom'

export type SelectorType = 'css' | 'role' | 'text' | 'testid' | 'placeholder' | 'label'

export interface Step {
  id: string
  action: StepAction
  name?: string
  url?: string
  selector?: string
  selectorType?: SelectorType
  value?: string
  key?: string
  timeoutMs?: number
  attribute?: string
  code?: string
}

export interface Project {
  id: number
  name: string
  description: string
  base_url: string
  default_browser: string
  default_timeout_ms: number
  created_at: string
  updated_at: string
  case_count: number
}

export type CaseMode = 'steps' | 'script'

export interface Case {
  id: number
  project_id: number
  name: string
  description: string
  tags: string[]
  enabled: boolean
  mode: CaseMode
  steps: Step[]
  script: string
  created_at: string
  updated_at: string
}

export interface Task {
  id: number
  project_id: number
  name: string
  case_ids: number[]
  browser: string
  headless: boolean
  retries: number
  timeout_ms: number
  created_at: string
}

export interface ArtifactItem {
  type: 'screenshot' | 'video' | string
  path: string
  label: string
}

export interface CaseResult {
  id: number
  run_id: number
  case_id: number
  case_name: string
  status: string
  duration_ms: number
  error_message: string
  error_type: string
  screenshot_path: string
  artifacts?: ArtifactItem[]
  step_results: Array<{
    index: number
    name: string
    action: string
    status: string
    duration_ms: number
    error: string
  }>
}

export interface RunLogEntry {
  type?: string
  level?: string
  message?: string
}

export interface Run {
  id: number
  task_id: number
  status: string
  started_at: string | null
  finished_at: string | null
  total: number
  passed: number
  failed: number
  skipped: number
  duration_ms: number
  error_summary: string
  created_at: string
  allure_results_path?: string
  allure_report_path?: string
  task_name?: string
  project_id?: number
  project_name?: string
  case_results?: CaseResult[]
  logs?: RunLogEntry[]
}

export interface AllureStatus {
  run_id: number
  has_results: boolean
  has_report: boolean
  results_path?: string | null
  report_path?: string | null
  report_url?: string | null
  allure_cli: boolean
  status?: string | null
  total?: number | null
  passed?: number | null
  failed?: number | null
  skipped?: number | null
  duration_ms?: number | null
  pass_rate?: number | null
  error_summary?: string | null
  failed_cases: Array<{
    case_id: number
    case_name: string
    status: string
    error_message: string
    error_type: string
    screenshot_path: string
    artifacts: Array<{ type: string; path: string; label: string }>
    duration_ms: number
  }>
}

export interface AllureGenerateResult {
  ok: boolean
  run_id: number
  results_path: string
  report_path: string
  report_url: string
}

export interface AnalyticsSummary {
  total_runs: number
  total_cases_executed: number
  pass_rate: number
  avg_duration_ms: number
  recent_pass_rates: Array<{ run_id: number; label: string; pass_rate: number; status: string }>
  failure_top: Array<{ error_type: string; count: number }>
  slowest_cases: Array<{ case_name: string; avg_duration_ms: number; samples: number }>
}
