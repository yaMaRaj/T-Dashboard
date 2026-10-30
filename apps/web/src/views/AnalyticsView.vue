<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { AnalyticsSummary } from '@/types'

const summary = ref<AnalyticsSummary | null>(null)
const error = ref('')

function fmtMs(ms: number) {
  if (!ms) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

onMounted(async () => {
  try {
    summary.value = await api.analytics()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>数据分析</h1>
        <p>通过率趋势、失败类型与慢用例</p>
      </div>
      <button class="btn" @click="api.analytics().then((s) => (summary = s))">刷新</button>
    </div>

    <p v-if="error" class="badge failed">{{ error }}</p>

    <template v-if="summary">
      <div class="grid-stats">
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

      <div class="charts">
        <div class="panel">
          <h2 style="margin: 0 0 16px; font-size: 1.05rem">最近通过率</h2>
          <div v-if="!summary.recent_pass_rates.length" class="empty">暂无数据</div>
          <div v-else class="bars">
            <div v-for="item in summary.recent_pass_rates" :key="item.run_id" class="bar-row">
              <div class="bar-label mono">{{ item.label }}</div>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${item.pass_rate}%` }" />
              </div>
              <div class="bar-value mono">{{ item.pass_rate }}%</div>
            </div>
          </div>
        </div>

        <div class="panel">
          <h2 style="margin: 0 0 16px; font-size: 1.05rem">失败类型 Top</h2>
          <table v-if="summary.failure_top.length" class="table">
            <thead>
              <tr>
                <th>错误类型</th>
                <th>次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="f in summary.failure_top" :key="f.error_type">
                <td class="mono">{{ f.error_type }}</td>
                <td>{{ f.count }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">暂无失败记录</div>
        </div>

        <div class="panel" style="grid-column: 1 / -1">
          <h2 style="margin: 0 0 16px; font-size: 1.05rem">最慢用例</h2>
          <table v-if="summary.slowest_cases.length" class="table">
            <thead>
              <tr>
                <th>用例</th>
                <th>平均耗时</th>
                <th>样本数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in summary.slowest_cases" :key="c.case_name">
                <td>{{ c.case_name }}</td>
                <td>{{ fmtMs(c.avg_duration_ms) }}</td>
                <td>{{ c.samples }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">暂无数据</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.charts {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
}

.bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bar-row {
  display: grid;
  grid-template-columns: 48px 1fr 56px;
  gap: 10px;
  align-items: center;
}

.bar-track {
  height: 10px;
  background: var(--bg);
  border-radius: 999px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #2f7ec8, var(--accent));
  border-radius: 999px;
}

.bar-value {
  text-align: right;
  color: var(--text-muted);
}

@media (max-width: 900px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>
