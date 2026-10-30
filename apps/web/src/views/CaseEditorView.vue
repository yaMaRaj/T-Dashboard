<script setup lang="ts">
/**
 * Case editor: visual steps vs Python script mode, save / generate-script / export.
 */
import { computed, onMounted, ref, toRaw, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Case, CaseMode, Step, StepAction } from '@/types'
import { createLogger } from '@/utils/logger'

const log = createLogger('case-editor')

/** Deep-copy steps; structuredClone fails on Vue reactive Proxies. */
function cloneSteps(src: Step[] | null | undefined): Step[] {
  return JSON.parse(JSON.stringify(toRaw(src) || [])) as Step[]
}

const props = defineProps<{ projectId: string; caseId: string }>()
const router = useRouter()
const caseId = computed(() => Number(props.caseId))
const projectId = computed(() => Number(props.projectId))

const item = ref<Case | null>(null)
const steps = ref<Step[]>([])
const script = ref('')
const generated = ref('')
const activeTab = ref<'steps' | 'script'>('steps')
const mode = ref<CaseMode>('steps')
const scriptDirty = ref(false)
const saving = ref(false)
const message = ref('')
const error = ref('')

const ACTIONS: { value: StepAction; label: string }[] = [
  { value: 'navigate', label: '导航' },
  { value: 'click', label: '点击' },
  { value: 'fill', label: '填写' },
  { value: 'select', label: '选择' },
  { value: 'hover', label: '悬停' },
  { value: 'press', label: '按键' },
  { value: 'wait', label: '等待' },
  { value: 'assert_visible', label: '断言可见' },
  { value: 'assert_text', label: '断言文本' },
  { value: 'assert_url', label: '断言 URL' },
  { value: 'assert_attribute', label: '断言属性' },
]

function uid() {
  return `s_${Math.random().toString(36).slice(2, 9)}`
}

function addStep() {
  steps.value.push({
    id: uid(),
    action: 'click',
    name: '新步骤',
    selectorType: 'css',
    selector: '',
  })
}

function removeStep(index: number) {
  steps.value.splice(index, 1)
}

function moveStep(index: number, delta: number) {
  const next = index + delta
  if (next < 0 || next >= steps.value.length) return
  const copy = [...steps.value]
  const [row] = copy.splice(index, 1)
  copy.splice(next, 0, row)
  steps.value = copy
}

async function load() {
  item.value = await api.getCase(caseId.value)
  steps.value = cloneSteps(item.value.steps)
  mode.value = item.value.mode || 'steps'
  script.value = item.value.script || ''
  scriptDirty.value = false
  const exported = await api.exportCaseCode(caseId.value)
  generated.value = exported.generated
  if (!script.value) {
    script.value = exported.generated
  }
  activeTab.value = mode.value === 'script' ? 'script' : 'steps'
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

watch(script, () => {
  if (item.value) scriptDirty.value = true
})

function stepsPayload() {
  // Omit steps when empty so script/regenerate never overwrite DB steps with [].
  // Intentional clear: use「保存步骤」with mode=steps (backend allows that path).
  if (!steps.value.length) return {}
  return { steps: steps.value }
}

async function saveSteps() {
  if (!item.value) return
  saving.value = true
  message.value = ''
  error.value = ''
  log.info(`save steps case=${caseId.value} count=${steps.value.length}`)
  try {
    item.value = await api.updateCase(caseId.value, {
      name: item.value.name,
      description: item.value.description,
      tags: item.value.tags,
      enabled: item.value.enabled,
      mode: 'steps',
      steps: steps.value,
    })
    mode.value = 'steps'
    steps.value = cloneSteps(item.value.steps)
    script.value = item.value.script || ''
    generated.value = script.value
    scriptDirty.value = false
    message.value = '步骤已保存（执行将按步骤运行，并已同步生成脚本）'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function saveScript() {
  if (!item.value) return
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    item.value = await api.updateCase(caseId.value, {
      name: item.value.name,
      description: item.value.description,
      tags: item.value.tags,
      enabled: item.value.enabled,
      mode: 'script',
      script: script.value,
      ...stepsPayload(),
    })
    mode.value = 'script'
    steps.value = cloneSteps(item.value.steps)
    scriptDirty.value = false
    message.value = '脚本已保存（执行将按 Playwright 脚本运行）'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function regenerateFromSteps() {
  if (!item.value) return
  // persist steps first so generate uses latest
  saving.value = true
  error.value = ''
  try {
    await api.updateCase(caseId.value, {
      name: item.value.name,
      description: item.value.description,
      tags: item.value.tags,
      enabled: item.value.enabled,
      mode: mode.value,
      script: script.value,
      ...stepsPayload(),
    })
    item.value = await api.generateScript(caseId.value)
    steps.value = cloneSteps(item.value.steps)
    script.value = item.value.script || ''
    generated.value = script.value
    scriptDirty.value = false
    message.value = '已从步骤重新生成脚本（未改变执行模式）'
    activeTab.value = 'script'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function saveMeta() {
  if (!item.value) return
  await api.updateCase(caseId.value, {
    name: item.value.name,
    description: item.value.description,
    tags: item.value.tags,
    enabled: item.value.enabled,
  })
}

function needsSelector(action: StepAction) {
  return !['navigate', 'wait', 'assert_url', 'custom'].includes(action)
}

function needsValue(action: StepAction) {
  return ['fill', 'select', 'assert_text', 'assert_attribute', 'assert_url'].includes(action)
}
</script>

<template>
  <div v-if="item">
    <div class="page-header">
      <div>
        <button class="btn btn-ghost" style="margin-bottom: 8px" @click="router.push(`/projects/${projectId}`)">
          ← 返回项目
        </button>
        <h1>编辑用例</h1>
        <p>
          步骤编排与 Playwright 脚本可切换；
          <span class="badge" :class="mode === 'script' ? 'running' : 'passed'">
            当前执行：{{ mode === 'script' ? '脚本模式' : '步骤模式' }}
          </span>
        </p>
      </div>
      <div class="row-actions">
        <button
          v-if="activeTab === 'steps'"
          class="btn btn-primary"
          :disabled="saving"
          @click="saveSteps"
        >
          {{ saving ? '保存中…' : '保存步骤' }}
        </button>
        <button
          v-else
          class="btn btn-primary"
          :disabled="saving"
          @click="saveScript"
        >
          {{ saving ? '保存中…' : '保存脚本并设为脚本模式' }}
        </button>
      </div>
    </div>

    <p v-if="message" class="badge passed">{{ message }}</p>
    <p v-if="error" class="badge failed">{{ error }}</p>

    <div class="panel" style="margin-bottom: 16px">
      <div class="form-grid" style="grid-template-columns: 1fr 1fr; gap: 12px">
        <div class="field">
          <label>名称</label>
          <input v-model="item.name" @change="saveMeta" />
        </div>
        <div class="field">
          <label>标签（逗号分隔）</label>
          <input
            :value="item.tags.join(', ')"
            @input="item.tags = ($event.target as HTMLInputElement).value.split(',').map(s => s.trim()).filter(Boolean)"
            @change="saveMeta"
          />
        </div>
        <div class="field" style="grid-column: 1 / -1">
          <label>描述</label>
          <textarea v-model="item.description" @change="saveMeta" />
        </div>
        <label style="display: flex; align-items: center; gap: 8px">
          <input v-model="item.enabled" type="checkbox" @change="saveMeta" />
          启用用例
        </label>
      </div>
    </div>

    <div class="tabs">
      <button class="tab" :class="{ active: activeTab === 'steps' }" @click="activeTab = 'steps'">
        步骤编排
      </button>
      <button class="tab" :class="{ active: activeTab === 'script' }" @click="activeTab = 'script'">
        Playwright 脚本
        <span v-if="scriptDirty" class="dot" />
      </button>
    </div>

    <div v-show="activeTab === 'steps'" class="panel">
      <div class="page-header" style="margin-bottom: 12px">
        <h2 style="margin: 0; font-size: 1.05rem">步骤列表</h2>
        <div class="row-actions">
          <button class="btn" @click="addStep">添加步骤</button>
          <button class="btn" :disabled="saving" @click="regenerateFromSteps">从步骤生成脚本</button>
        </div>
      </div>

      <div v-if="!steps.length" class="empty">暂无步骤，点击「添加步骤」开始编排。</div>

      <div v-for="(step, index) in steps" :key="step.id" class="step-card">
        <div class="step-head">
          <strong class="mono">#{{ index + 1 }}</strong>
          <input v-model="step.name" class="step-name" placeholder="步骤名称" />
          <div class="row-actions">
            <button class="btn btn-ghost" @click="moveStep(index, -1)">↑</button>
            <button class="btn btn-ghost" @click="moveStep(index, 1)">↓</button>
            <button class="btn btn-danger" @click="removeStep(index)">删</button>
          </div>
        </div>

        <div class="step-body">
          <div class="field">
            <label>动作</label>
            <select v-model="step.action">
              <option v-for="a in ACTIONS" :key="a.value" :value="a.value">{{ a.label }}</option>
            </select>
          </div>

          <div v-if="step.action === 'navigate'" class="field">
            <label>URL</label>
            <input v-model="step.url" placeholder="https://… 或 /path" />
          </div>

          <template v-if="needsSelector(step.action)">
            <div class="field">
              <label>选择器类型</label>
              <select v-model="step.selectorType">
                <option value="css">CSS</option>
                <option value="text">文本</option>
                <option value="role">Role</option>
                <option value="testid">TestId</option>
                <option value="placeholder">Placeholder</option>
                <option value="label">Label</option>
              </select>
            </div>
            <div class="field">
              <label>选择器</label>
              <input v-model="step.selector" placeholder="#login / Get started / button" />
            </div>
          </template>

          <div v-if="needsValue(step.action)" class="field">
            <label>{{ step.action === 'assert_url' ? 'URL 包含' : '值' }}</label>
            <input v-model="step.value" />
          </div>

          <div v-if="step.action === 'press'" class="field">
            <label>按键</label>
            <input v-model="step.key" placeholder="Enter" />
          </div>

          <div v-if="step.action === 'assert_attribute'" class="field">
            <label>属性名</label>
            <input v-model="step.attribute" placeholder="href" />
          </div>

          <div v-if="step.action === 'wait'" class="field">
            <label>等待毫秒</label>
            <input v-model.number="step.timeoutMs" type="number" min="0" />
          </div>
        </div>
      </div>
    </div>

    <div v-show="activeTab === 'script'" class="panel">
      <div class="page-header" style="margin-bottom: 12px">
        <div>
          <h2 style="margin: 0; font-size: 1.05rem">Playwright Python 脚本</h2>
          <p class="muted" style="margin: 6px 0 0; font-size: 0.85rem">
            可直接编辑。保存后切换为「脚本模式」，运行任务时会执行此脚本。
            也可用「从步骤重新生成」覆盖当前内容。
          </p>
        </div>
        <div class="row-actions">
          <button class="btn" :disabled="saving" @click="regenerateFromSteps">从步骤重新生成</button>
          <button class="btn btn-primary" :disabled="saving" @click="saveScript">保存脚本</button>
        </div>
      </div>
      <textarea
        v-model="script"
        class="script-editor mono"
        spellcheck="false"
        placeholder="# Playwright sync_api script"
      />
    </div>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.tab {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-muted);
  border-radius: 8px 8px 0 0;
  padding: 10px 16px;
  position: relative;
}

.tab.active {
  color: var(--text);
  background: var(--bg-soft);
  border-bottom-color: var(--bg-soft);
}

.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--warning);
}

.step-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
  background: var(--bg);
}

.step-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.step-name {
  flex: 1;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  padding: 6px 10px;
}

.step-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.script-editor {
  width: 100%;
  min-height: 520px;
  resize: vertical;
  background: #0b1015;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 14px;
  line-height: 1.55;
  tab-size: 4;
}

@media (max-width: 1000px) {
  .step-body {
    grid-template-columns: 1fr;
  }
}
</style>
