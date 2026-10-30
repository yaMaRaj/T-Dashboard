<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { AnalyticsSummary, Run } from '@/types'

const router = useRouter()
const summary = ref<AnalyticsSummary | null>(null)
const runs = ref<Run[]>([])
const error = ref('')

onMounted(async () => {
  try {
    ;[summary.value, runs.value] = await Promise.all([api.analytics(), api.listRuns()])
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

function fmtMs(ms: number) {
  if (!ms) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>概览</h1>
        <p>本机 Playwright 自动化测试控制台</p>
      </div>
      <button class="btn btn-primary" @click="router.push('/projects')">管理项目</button>
    </div>

    <p v-if="error" class="badge failed">{{ error }}</p>

    <div v-if="summary" class="grid-stats">
      <div class="stat">
        <div class="label">运行次数</div>
        <div class="value">{{ summary.total_runs }}</div>
      </div>
      <div class="stat">
        <div class="label">用例执行数</div>
        <div class="value">{{ summary.total_cases_executed }}</div>
      </div>
      <div class="stat">
        <div class="label">通过率</div>
        <div class="value">{{ summary.pass_rate }}%</div>
      </div>
      <div class="stat">
        <div class="label">平均耗时</div>
        <div class="value">{{ fmtMs(summary.avg_duration_ms) }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="page-header" style="margin-bottom: 8px">
        <h2 style="margin: 0; font-size: 1.1rem">最近运行</h2>
        <button class="btn btn-ghost" @click="router.push('/runs')">查看全部</button>
      </div>
      <table v-if="runs.length" class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>任务</th>
            <th>项目</th>
            <th>状态</th>
            <th>通过/失败</th>
            <th>耗时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs.slice(0, 8)" :key="run.id" style="cursor: pointer" @click="router.push(`/runs/${run.id}`)">
            <td class="mono">#{{ run.id }}</td>
            <td>{{ run.task_name || `Task #${run.task_id}` }}</td>
            <td>{{ run.project_name || '—' }}</td>
            <td><span class="badge" :class="run.status">{{ run.status }}</span></td>
            <td class="mono">{{ run.passed }}/{{ run.failed }}</td>
            <td>{{ fmtMs(run.duration_ms) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无运行记录。创建项目后即可发起测试任务。</div>
    </div>
  </div>
</template>
