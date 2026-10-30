<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Project } from '@/types'

const router = useRouter()
const projects = ref<Project[]>([])
const showForm = ref(false)
const form = reactive({
  name: '',
  description: '',
  base_url: '',
  default_browser: 'chromium',
})
const error = ref('')

async function load() {
  projects.value = await api.listProjects()
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

async function createProject() {
  if (!form.name.trim()) return
  await api.createProject({ ...form })
  showForm.value = false
  form.name = ''
  form.description = ''
  form.base_url = ''
  await load()
}

async function removeProject(id: number) {
  if (!confirm('确定删除该项目及其用例？')) return
  await api.deleteProject(id)
  await load()
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>项目与用例</h1>
        <p>按被测系统组织用例库</p>
      </div>
      <button class="btn btn-primary" @click="showForm = !showForm">
        {{ showForm ? '取消' : '新建项目' }}
      </button>
    </div>

    <p v-if="error" class="badge failed">{{ error }}</p>

    <div v-if="showForm" class="panel" style="margin-bottom: 16px">
      <div class="form-grid">
        <div class="field">
          <label>项目名称</label>
          <input v-model="form.name" placeholder="例如：官网冒烟" />
        </div>
        <div class="field">
          <label>Base URL</label>
          <input v-model="form.base_url" placeholder="https://example.com" />
        </div>
        <div class="field">
          <label>描述</label>
          <textarea v-model="form.description" />
        </div>
        <div class="field">
          <label>默认浏览器</label>
          <select v-model="form.default_browser">
            <option value="chromium">Chromium</option>
            <option value="firefox">Firefox</option>
            <option value="webkit">WebKit</option>
          </select>
        </div>
        <div>
          <button class="btn btn-primary" @click="createProject">创建</button>
        </div>
      </div>
    </div>

    <div class="panel">
      <table v-if="projects.length" class="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>Base URL</th>
            <th>用例数</th>
            <th>浏览器</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects" :key="p.id">
            <td>
              <a @click.prevent="router.push(`/projects/${p.id}`)" style="color: var(--accent); cursor: pointer">
                {{ p.name }}
              </a>
              <div class="muted" style="font-size: 0.8rem">{{ p.description || '无描述' }}</div>
            </td>
            <td class="mono">{{ p.base_url || '—' }}</td>
            <td>{{ p.case_count }}</td>
            <td>{{ p.default_browser }}</td>
            <td class="row-actions">
              <button class="btn" @click="router.push(`/projects/${p.id}`)">打开</button>
              <button class="btn btn-danger" @click="removeProject(p.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">还没有项目。可使用内置 Demo，或新建一个项目。</div>
    </div>
  </div>
</template>
