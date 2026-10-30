/** Client-side routes for the T-Dashboard SPA. */

import { createRouter, createWebHistory } from 'vue-router'
import { createLogger } from '@/utils/logger'

const log = createLogger('router')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/projects', name: 'projects', component: () => import('@/views/ProjectsView.vue') },
    {
      path: '/projects/:id',
      name: 'project-detail',
      component: () => import('@/views/ProjectDetailView.vue'),
      props: true,
    },
    {
      path: '/projects/:projectId/cases/:caseId',
      name: 'case-editor',
      component: () => import('@/views/CaseEditorView.vue'),
      props: true,
    },
    { path: '/runs', name: 'runs', component: () => import('@/views/RunsView.vue') },
    {
      path: '/runs/:id',
      name: 'run-detail',
      component: () => import('@/views/RunDetailView.vue'),
      props: true,
    },
    { path: '/analytics', name: 'analytics', component: () => import('@/views/AnalyticsView.vue') },
  ],
})

router.afterEach((to, from) => {
  log.debug(`nav ${String(from.name || from.path)} → ${String(to.name || to.path)}`)
})

export default router
