<script setup lang="ts">
/** Shell layout: sidebar nav + Chromium readiness banner. */
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { createLogger } from '@/utils/logger'

const log = createLogger('app')
const pwStatus = ref<{ installed: boolean; message: string; hint?: string } | null>(null)

onMounted(async () => {
  try {
    pwStatus.value = await api.playwrightStatus()
    log.info(`playwright: ${pwStatus.value?.message}`)
  } catch (e) {
    log.error('backend unreachable', e)
    pwStatus.value = { installed: false, message: '无法连接后端', hint: '请先启动 FastAPI 服务' }
  }
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">T-Dashboard</div>
        <div class="brand-sub">Playwright 测试控制台</div>
      </div>
      <nav class="nav">
        <router-link to="/">概览</router-link>
        <router-link to="/projects">项目与用例</router-link>
        <router-link to="/runs">运行历史</router-link>
        <router-link to="/analytics">数据分析</router-link>
      </nav>
      <div v-if="pwStatus" class="pw-status">
        <div class="muted" style="font-size: 0.8rem; margin-bottom: 6px">Playwright</div>
        <span class="badge" :class="pwStatus.installed ? 'passed' : 'failed'">
          {{ pwStatus.installed ? '就绪' : '未就绪' }}
        </span>
        <p v-if="!pwStatus.installed" class="muted" style="font-size: 0.75rem; margin-top: 8px">
          {{ pwStatus.hint || pwStatus.message }}
        </p>
      </div>
    </aside>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.pw-status {
  margin-top: auto;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-soft);
}
</style>
