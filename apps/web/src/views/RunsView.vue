<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Run } from '@/types'

const router = useRouter()
const runs = ref<Run[]>([])
const error = ref('')

function fmtMs(ms: number) {
  if (!ms) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

onMounted(async () => {
  try {
    runs.value = await api.listRuns()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>运行历史</h1>
        <p>查看每次任务执行结果</p>
      </div>
      <button class="btn" @click="api.listRuns().then((r) => (runs = r))">刷新</button>
    </div>

    <p v-if="error" class="badge failed">{{ error }}</p>

    <div class="panel">
      <table v-if="runs.length" class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>任务</th>
            <th>项目</th>
            <th>状态</th>
            <th>通过</th>
            <th>失败</th>
            <th>跳过</th>
            <th>耗时</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="run in runs"
            :key="run.id"
            style="cursor: pointer"
            @click="router.push(`/runs/${run.id}`)"
          >
            <td class="mono">#{{ run.id }}</td>
            <td>{{ run.task_name || `Task #${run.task_id}` }}</td>
            <td>{{ run.project_name || '—' }}</td>
            <td><span class="badge" :class="run.status">{{ run.status }}</span></td>
            <td>{{ run.passed }}</td>
            <td>{{ run.failed }}</td>
            <td>{{ run.skipped }}</td>
            <td>{{ fmtMs(run.duration_ms) }}</td>
            <td class="muted">{{ new Date(run.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无运行记录。</div>
    </div>
  </div>
</template>
