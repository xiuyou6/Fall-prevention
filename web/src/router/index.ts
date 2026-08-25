import { createRouter, createWebHistory } from 'vue-router'

import type { UserRole } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    title: string
    roles?: UserRole[]
    elderScreen?: boolean
  }
}

export default createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', redirect: '/dashboard', meta: { title: '首页' } },
    { path: '/login', component: () => import('../views/LoginView.vue'), meta: { public: true, title: '登录' } },
    { path: '/dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '安全总览', roles: ['admin', 'family'] } },
    { path: '/elders', component: () => import('../views/EldersView.vue'), meta: { title: '关怀对象', roles: ['admin', 'family'] } },
    { path: '/alerts', component: () => import('../views/AlertsView.vue'), meta: { title: '告警中心', roles: ['admin', 'family'] } },
    { path: '/elders/:elderId/monitor', component: () => import('../views/MonitorView.vue'), meta: { title: '实时监测', roles: ['admin', 'family'] } },
    { path: '/elders/:elderId/video-analysis/:jobId', name: 'video-analysis', component: () => import('../views/VideoAnalysisView.vue'), meta: { title: '视频分析', roles: ['admin', 'family'] } },
    { path: '/authorization', component: () => import('../views/AuthorizationView.vue'), meta: { title: '授权与绑定', roles: ['admin'] } },
    { path: '/elder-home', component: () => import('../views/ElderHomeView.vue'), meta: { title: '老人安全页', roles: ['elder'], elderScreen: true } },
    { path: '/settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统诊断', roles: ['admin'] } },
    { path: '/accounts', component: () => import('../views/AccountsView.vue'), meta: { title: '账号管理', roles: ['admin'] } },
    { path: '/forbidden', component: () => import('../views/ForbiddenView.vue'), meta: { title: '无权访问' } },
    { path: '/:pathMatch(.*)*', component: () => import('../views/NotFoundView.vue'), meta: { title: '页面不存在' } },
  ],
})
