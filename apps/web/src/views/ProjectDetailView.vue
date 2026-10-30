<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Case, Project } from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const projectId = computed(() => Number(props.id))

const project = ref<Project | null>(null)
const cases = ref<Case[]>([])
const selected = ref<number[]>([])
const running = ref(false)
const taskName = ref('')
const showBrowser = ref(true)
const captureScreenshots = ref(false)
const recordVideo = ref(false)
const error = ref('')

function onCaptureToggle() {
  // Watching the window / recording works reliably in headed mode.
  if (captureScreenshots.value || recordVideo.value) {
    showBrowser.value = true
  }
}

const newCase = reactive({ name: '', description: '' })
const showNewCase = ref(false)

async function load() {
  project.value = await api.getProject(projectId.value)
  cases.value = await api.listCases(projectId.value)
  taskName.value = `${project.value.name} · 手动任务`
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

function toggle(id: number) {
  if (selected.value.includes(id)) {
    selected.value = selected.value.filter((x) => x !== id)
  } else {
    selected.value = [...selected.value, id]
  }
}

function toggleAll() {
  if (selected.value.length === cases.value.length) {
    selected.value = []
  } else {
    selected.value = cases.value.map((c) => c.id)
  }
}

async function createCase() {
  if (!newCase.name.trim()) return
  const created = await api.createCase(projectId.value, {
    name: newCase.name,
    description: newCase.description,
    steps: [],
  })
  showNewCase.value = false
  newCase.name = ''
  newCase.description = ''
  await load()
  router.push(`/projects/${projectId.value}/cases/${created.id}`)
}

async function removeCase(id: number) {
  if (!confirm('删除该用例？')) return
  await api.deleteCase(id)
  selected.value = selected.value.filter((x) => x !== id)
  await load()
}

async function runSelected() {
  if (!selected.value.length || !project.value) return
  running.value = true
  try {
    const { run } = await api.createTask(projectId.value, {
      name: taskName.value || '手动任务',
      case_ids: selected.value,
      browser: project.value.default_browser,
      headless: !showBrowser.value,
      timeout_ms: project.value.default_timeout_ms,
      capture_screenshots: captureScreenshots.value,
      record_video: recordVideo.value,
      run_immediately: true,
    })
    if (run) router.push(`/runs/${run.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    running.value = false
  }
}
</script>

<template>
  <div v-if="project">
    <div class="page-header">
      <div>
        <button class="btn btn-ghost" style="margin-bottom: 8px" @click="router.push('/projects')">← 项目列表</button>
        <h1>{{ project.name }}</h1>
        <p>{{ project.description || project.base_url || '无描述' }}</p>
      </div>
      <div class="row-actions">
        <button class="btn" @click="showNewCase = !showNewCase">新建用例</button>
        <button class="btn btn-primary" :disabled="!selected.length || running" @click="runSelected">
          {{ running ? '启动中…' : `运行选中 (${selected.length})` }}
        </button>
      </div>
    </div>

    <p v-if="error" class="badge failed">{{ error }}</p>

    <div v-if="showNewCase" class="panel" style="margin-bottom: 16px">
      <div class="form-grid">
        <div class="field">
          <label>用例名称</label>
          <input v-model="newCase.name" placeholder="登录成功" />
        </div>
        <div class="field">
          <label>描述</label>
          <textarea v-model="newCase.description" />
        </div>
        <div>
          <button class="btn btn-primary" @click="createCase">创建并编辑步骤</button>
        </div>
      </div>
    </div>

    <div class="panel" style="margin-bottom: 16px">
      <div class="field">
        <label>任务名称</label>
        <input v-model="taskName" />
      </div>
      <div class="capture-opts">
        <label class="check">
          <input v-model="showBrowser" type="checkbox" />
          显示浏览器窗口（观看自动化；结束后窗口保留，可继续手动操作）
        </label>
        <label class="check">
          <input v-model="captureScreenshots" type="checkbox" @change="onCaptureToggle" />
          步骤模式：自动化阶段页面变动时截图
        </label>
        <label class="check">
          <input v-model="recordVideo" type="checkbox" @change="onCaptureToggle" />
          步骤模式：自动化阶段全程录像
        </label>
        <p class="muted" style="font-size: 0.8rem; margin: 4px 0 0">
          截图/录像只在自动化步骤期间采集；自动化结束后停止录制，浏览器保持打开直到你手动关闭。
        </p>
      </div>
    </div>

    <div class="panel">
      <table v-if="cases.length" class="table">
        <thead>
          <tr>
            <th style="width: 40px">
              <input type="checkbox" :checked="selected.length === cases.length" @change="toggleAll" />
            </th>
            <th>用例</th>
            <th>标签</th>
            <th>步骤</th>
            <th>状态</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in cases" :key="c.id">
            <td>
              <input type="checkbox" :checked="selected.includes(c.id)" @change="toggle(c.id)" />
            </td>
            <td>
              <a
                style="color: var(--accent); cursor: pointer"
                @click.prevent="router.push(`/projects/${projectId}/cases/${c.id}`)"
              >
                {{ c.name }}
              </a>
              <div class="muted" style="font-size: 0.8rem">{{ c.description || '无描述' }}</div>
            </td>
            <td>
              <span v-for="tag in c.tags" :key="tag" class="badge" style="margin-right: 4px">{{ tag }}</span>
              <span v-if="!c.tags?.length" class="muted">—</span>
            </td>
            <td>
              {{ c.steps?.length || 0 }}
              <span class="badge" style="margin-left: 6px" :class="c.mode === 'script' ? 'running' : ''">
                {{ c.mode === 'script' ? '脚本' : '步骤' }}
              </span>
            </td>
            <td>
              <span class="badge" :class="c.enabled ? 'passed' : 'failed'">
                {{ c.enabled ? '启用' : '禁用' }}
              </span>
            </td>
            <td class="row-actions">
              <button class="btn" @click="router.push(`/projects/${projectId}/cases/${c.id}`)">编辑</button>
              <button class="btn btn-danger" @click="removeCase(c.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">该项目还没有用例。</div>
    </div>
  </div>
</template>

<style scoped>
.capture-opts {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.check {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--text-muted);
  font-size: 0.9rem;
}
</style>
