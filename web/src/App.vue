<template>
  <RouterView v-if="isStandalonePage" />
  <div v-else class="app-frame">
    <a class="skip-link" href="#main-content">跳至主要内容</a>
    <aside class="sidebar" :class="{ 'is-open': mobileOpen }" aria-label="主导航">
      <div class="brand">
        <div class="brand-mark"><FirstAidKit /></div>
        <div><strong>安步守护</strong><span>Fall prevention</span></div>
        <button class="icon-button close-button" aria-label="关闭导航" @click="mobileOpen = false"><Close /></button>
      </div>
      <div class="role-chip"><span class="role-dot" />{{ roleLabel }}</div>
      <nav class="main-nav">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" class="nav-link" @click="mobileOpen = false">
          <component :is="item.icon" /><span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <div class="avatar">{{ userInitial }}</div>
        <div><strong>{{ userName }}</strong><span>{{ roleLabel }}</span></div>
      </div>
    </aside>
    <div class="sidebar-backdrop" :class="{ 'is-visible': mobileOpen }" @click="mobileOpen = false" />
    <section class="workspace">
      <header class="topbar">
        <button class="icon-button menu-button" aria-label="打开导航" @click="mobileOpen = true"><Menu /></button>
        <div class="crumb"><span>安步守护</span><i>/</i><strong>{{ route.meta.title }}</strong></div>
        <div class="topbar-actions">
          <el-popover placement="bottom-end" :width="340" trigger="click" @show="loadNotices">
            <template #reference>
              <button class="notification" aria-label="查看消息"><Bell /><b v-if="openNotices.length">{{ openNotices.length }}</b></button>
            </template>
            <div class="notice-head"><b>消息通知</b><RouterLink to="/alerts">查看全部</RouterLink></div>
            <el-empty v-if="!openNotices.length" description="暂无待处理消息" :image-size="56" />
            <div v-for="item in openNotices.slice(0, 5)" :key="item.alertId" class="notice-item">
              <b>{{ item.elderName }}</b><p>{{ item.message }}</p><small>{{ formatTime(item.createdAt) }}</small>
            </div>
          </el-popover>
          <el-dropdown>
            <span class="user-menu"><i>{{ userInitial }}</i>{{ userName }}<el-icon><ArrowDown /></el-icon></span>
            <template #dropdown><el-dropdown-menu><el-dropdown-item @click="logout"><SwitchButton />退出登录</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </header>
      <main id="main-content" class="main-content"><RouterView /></main>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ArrowDown, Bell, Close, Connection, DataAnalysis, FirstAidKit, Lock, Menu, SwitchButton, UserFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import type { Result } from './api/types'
import { useAuthStore } from './stores/auth'
import request from './utils/request'

interface Notice {
  alertId: string
  elderName: string
  message: string
  status: string
  createdAt: string
}

const ALERT_POLL_MS = 10_000
const route = useRoute()
const auth = useAuthStore()
const mobileOpen = ref(false)
const notices = ref<Notice[]>([])
const seenAlertStates = new Map<string, string>()
let pollTimer: number | undefined

const isStandalonePage = computed(() => route.meta.elderScreen === true || route.meta.public === true)
const userName = computed(() => auth.user.value?.displayName || '未登录')
const userInitial = computed(() => userName.value.slice(0, 1))
const roleLabel = computed(() => ({ admin: '系统管理员', family: '家属', elder: '老人' }[auth.user.value?.role || 'family']))
const openNotices = computed(() => notices.value.filter((item) => ['pending', 'confirmed', 'processing'].includes(item.status)))
const navigation = computed(() => {
  const common = [
    { to: '/dashboard', label: '安全总览', icon: DataAnalysis },
    { to: '/elders', label: auth.user.value?.role === 'family' ? '我的家人' : '关怀对象', icon: UserFilled },
    { to: '/alerts', label: '告警中心', icon: Bell },
  ]
  if (auth.user.value?.role !== 'admin') return common
  return [
    ...common,
    { to: '/accounts', label: '账号管理', icon: UserFilled },
    { to: '/authorization', label: '授权与绑定', icon: Connection },
    { to: '/settings', label: '系统诊断', icon: Lock },
  ]
})

function formatTime(value: string): string {
  return value?.replace('T', ' ').slice(0, 16) || '-'
}

async function loadNotices(): Promise<void> {
  if (!auth.user.value || auth.user.value.role === 'elder') return
  try {
    const response = await request.get<Result<Notice[]>>('/alerts', { params: { status: 'pending,confirmed,processing' }, headers: { 'X-Silent-Error': '1' } })
    const next = response.data.data
    const changedAlerts = next.filter((item) => {
      const previous = seenAlertStates.get(item.alertId)
      return previous === undefined || previous !== item.status
    })
    const firstLoad = seenAlertStates.size === 0
    next.forEach((item) => seenAlertStates.set(item.alertId, item.status))
    notices.value = next
    if (changedAlerts.length && !firstLoad) {
      ElMessage.warning(`收到 ${changedAlerts.length} 条新的安全告警或状态更新`)
      window.speechSynthesis?.speak(new SpeechSynthesisUtterance('收到新的安全告警，请及时查看。'))
    }
  } catch {
    notices.value = []
  }
}

async function logout(): Promise<void> {
  await auth.logout()
  window.location.assign('/login')
}

watch(() => auth.user.value?.role, () => {
  window.clearInterval(pollTimer)
  if (auth.user.value?.role !== 'elder') pollTimer = window.setInterval(loadNotices, ALERT_POLL_MS)
})

onMounted(async () => {
  await loadNotices()
  if (auth.user.value?.role !== 'elder') pollTimer = window.setInterval(loadNotices, ALERT_POLL_MS)
})
onBeforeUnmount(() => window.clearInterval(pollTimer))
</script>

<style scoped>
:global(html), :global(body), :global(#app) { width: 100%; height: 100%; overflow: hidden; }
.app-frame, .workspace { height: 100vh; overflow: hidden; }
.main-content { height: calc(100vh - 70px); overflow-y: auto; }
.sidebar { width: 224px; padding: 18px 12px; background: #001f3f; }
.brand { padding: 8px 10px 24px; }
.brand-mark { width: 34px; height: 34px; }
.main-nav { gap: 4px; }
.nav-link { min-height: 44px; padding: 0 12px; font-size: 14px; }
.nav-link :deep(svg) { width: 19px; height: 19px; flex: none; }
.nav-link span { white-space: nowrap; }
.workspace { margin-left: 224px; width: calc(100% - 224px); }
.notification { border: 0; background: transparent; padding: 7px; cursor: pointer; }
.notice-head { display: flex; justify-content: space-between; border-bottom: 1px solid #edf1f5; padding-bottom: 10px; }
.notice-item { padding: 10px 0; border-bottom: 1px solid #edf1f5; }
.notice-item p, .notice-item small { display: block; margin: 3px 0; color: #7892a4; font-size: 12px; }
:deep(.monitor-video) { width: 100%; min-height: 420px; object-fit: contain; background: #0f172a; border-radius: 6px; }
:deep(.hidden-canvas) { display: none; }
:deep(.ml-10) { margin-left: 10px; }
:deep(.mt-20) { margin-top: 20px; }
:deep(.w-full) { width: 100%; }
@media (max-width: 760px) { .workspace { margin-left: 0; width: 100%; } :deep(.monitor-video) { min-height: 260px; } }
</style>
