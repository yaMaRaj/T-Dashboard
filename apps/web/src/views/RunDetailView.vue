<script setup lang="ts">
/**
 * Run detail: status, case results, live WS logs, cancel, Allure report.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Run } from '@/types'
import { createLogger } from '@/utils/logger'

const log = createLogger('run-detail')
const props = defineProps<{ id: string }>()
const router = useRouter()
const runId = computed(() => Number(props.id))

const run = ref<Run | null>(null)
const logs = ref<string[]>([])
const error = ref('')
const allureBusy = ref(false)
let socket: WebSocket | null = null
let pollTimer: number | undefined

function fmtMs(ms: number) {
  if (!ms) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function artifactUrl(path: string) {
  if (!path) return ''
  const cleaned = path.replace(/^artifacts[\\/]/, '').replace(/\\/g, '/')
  return `/artifacts/${cleaned}`
}

function formatLogEntry(entry: { type?: string; level?: string; message?: string }) {
  if (entry.type === 'log' || (!entry.type && entry.message)) {
    return `[${entry.level || 'info'}] ${entry.message || ''}`
  }
  return entry.message || ''
}

function hydrateLogsFromRun() {
  // Prefer live WS stream once it has lines; otherwise restore persisted DB logs.
  if (logs.value.length > 0) return
  const stored = run.value?.logs
  if (!stored?.length) return
  logs.value = stored.map(formatLogEntry).filter(Boolean)
}

async function load() {
  run.value = await api.getRun(runId.value)
  hydrateLogsFromRun()
}

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${proto}://${location.host}/ws/runs/${runId.value}`)
  socket.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'ping') return
    if (data.type === 'log') {
      logs.value.push(`[${data.level}] ${data.message}`)
    } else if (data.type === 'case_started') {
      logs.value.push(`→ 开始用例: ${data.case_name}`)
    } else if (data.type === 'case_finished') {
      logs.value.push(`← 结束用例: ${data.case_name} (${data.status})`)
      load()
    } else if (data.type === 'run_finished') {
      logs.value.push(`■ 运行结束: ${data.status}`)
      load()
    } else if (data.type === 'run_started') {
      logs.value.push(`■ 运行开始，共 ${data.total} 条用例`)
      load()
    } else if (data.type === 'run_error') {
      logs.value.push(`[error] ${data.message}`)
      load()
    }
  }
}

onMounted(async () => {
  try {
    await load()
    connectWs()
    pollTimer = window.setInterval(() => {
      if (run.value && ['pending', 'running', 'cancelling'].includes(run.value.status)) {
        load()
      }
    }, 1000)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

onUnmounted(() => {
  socket?.close()
  if (pollTimer) clearInterval(pollTimer)
})

async function cancel() {
  log.info(`cancel run ${runId.value}`)
  await api.cancelRun(runId.value)
  logs.value.push('已请求取消…')
  await load()
}

const canOpenAllure = computed(() => {
  if (!run.value) return false
  return !['pending', 'running', 'cancelling'].includes(run.value.status)
})

async function openAllureReport() {
  if (!run.value) return
  allureBusy.value = true
  error.value = ''
  log.info(`open allure for run ${runId.value}`)
  try {
    const status = await api.getAllureStatus(runId.value)
    let url = status.report_url
    if (!url) {
      const generated = await api.generateAllureReport(runId.value)
      url = generated.report_url
      await load()
    }
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    log.error(`allure failed for run ${runId.value}`, error.value)
  } finally {
    allureBusy.value = false
  }
}
</script>

<template>
  <div v-if="run">
    <div class="page-header">
      <div>
        <button class="btn btn-ghost" style="margin-bottom: 8px" @click="router.push('/runs')">← 运行历史</button>
        <h1>运行 #{{ run.id }}</h1>
        <p>{{ run.task_name || `Task #${run.task_id}` }} · {{ run.project_name }}</p>
      </div>
      <div class="row-actions">
        <span class="badge" :class="run.status">{{ run.status }}</span>
        <button
          v-if="['pending', 'running'].includes(run.status)"
          class="btn btn-danger"
          @click="cancel"
        >
          取消
        </button>
        <span v-else-if="run.status === 'cancelling'" class="badge cancelled">取消中…</span>
        <button
          v-if="canOpenAllure"
          class="btn"
          :disabled="allureBusy"
          @click="openAllureReport"
        >
          {{ allureBusy ? '生成中…' : 'Allure 报告' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="badge failed">{{ error }}</p>

    <div class="grid-stats">
      <div class="stat">
        <div class="label">总计</div>
        <div class="value">{{ run.total }}</div>
      </div>
      <div class="stat">
        <div class="label">通过</div>
        <div class="value" style="color: var(--success)">{{ run.passed }}</div>
      </div>
      <div class="stat">
        <div class="label">失败</div>
        <div class="value" style="color: var(--danger)">{{ run.failed }}</div>
      </div>
      <div class="stat">
        <div class="label">耗时</div>
        <div class="value">{{ fmtMs(run.duration_ms) }}</div>
      </div>
    </div>

    <div class="detail-grid">
      <div class="panel">
        <h2 style="margin: 0 0 12px; font-size: 1.05rem">用例结果</h2>
        <div v-if="!run.case_results?.length" class="empty">等待执行结果…</div>
        <div v-for="cr in run.case_results" :key="cr.id" class="case-block">
          <div class="case-head">
            <strong>{{ cr.case_name }}</strong>
            <span class="badge" :class="cr.status">{{ cr.status }}</span>
            <span class="muted">{{ fmtMs(cr.duration_ms) }}</span>
          </div>
          <p v-if="cr.error_message" class="error-text mono">{{ cr.error_message }}</p>

          <div
            v-if="(cr.artifacts && cr.artifacts.length) || cr.screenshot_path"
            class="artifacts"
          >
            <h3 class="artifacts-title">产物</h3>
            <div class="shot-grid">
              <template v-for="(art, ai) in cr.artifacts || []" :key="ai">
                <figure v-if="art.type === 'screenshot'" class="shot-card">
                  <img class="shot" :src="artifactUrl(art.path)" :alt="art.label" />
                  <figcaption class="muted">{{ art.label }}</figcaption>
                </figure>
                <div v-else-if="art.type === 'video'" class="shot-card">
                  <video class="shot" controls :src="artifactUrl(art.path)" />
                  <div class="muted">{{ art.label }}</div>
                  <a class="btn" style="margin-top: 6px; display: inline-block" :href="artifactUrl(art.path)" download>
                    下载录像
                  </a>
                </div>
              </template>
              <figure
                v-if="cr.screenshot_path && !(cr.artifacts || []).some((a) => a.path === cr.screenshot_path)"
                class="shot-card"
              >
                <img class="shot" :src="artifactUrl(cr.screenshot_path)" alt="failure" />
                <figcaption class="muted">失败截图</figcaption>
              </figure>
            </div>
          </div>

          <table v-if="cr.step_results?.length" class="table">
            <thead>
              <tr>
                <th>#</th>
                <th>步骤</th>
                <th>动作</th>
                <th>状态</th>
                <th>耗时</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sr in cr.step_results" :key="sr.index">
                <td>{{ sr.index + 1 }}</td>
                <td>{{ sr.name }}</td>
                <td class="mono">{{ sr.action }}</td>
                <td><span class="badge" :class="sr.status">{{ sr.status }}</span></td>
                <td>{{ fmtMs(sr.duration_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <h2 style="margin: 0 0 12px; font-size: 1.05rem">实时日志</h2>
        <pre class="log mono">{{ logs.join('\n') || '等待日志…' }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
  align-items: start;
}

.case-block {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--bg);
}

.case-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.error-text {
  color: var(--danger);
  white-space: pre-wrap;
  font-size: 0.8rem;
}

.artifacts {
  margin: 10px 0 14px;
}

.artifacts-title {
  margin: 0 0 8px;
  font-size: 0.95rem;
}

.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.shot-card {
  margin: 0;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-elevated);
}

.shot {
  width: 100%;
  max-height: 240px;
  object-fit: contain;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: #0b1015;
}

.log {
  margin: 0;
  min-height: 320px;
  max-height: 640px;
  overflow: auto;
  background: #0b1015;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  white-space: pre-wrap;
  line-height: 1.5;
}

@media (max-width: 1000px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
