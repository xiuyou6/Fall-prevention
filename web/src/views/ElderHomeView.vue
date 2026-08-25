<template>
  <div class="elder-screen" :class="{ help: Boolean(alert) }">
    <header><div class="elder-brand"><FirstAidKit />安步守护</div><div><button class="button button-ghost" @click="checkinOpen = true">今日问询</button><button class="button button-ghost" @click="() => speak()"><Microphone />再次播报</button></div></header>
    <main v-loading="loading">
      <div class="elder-status-icon"><Bell v-if="alert" /><FirstAidKit v-else /></div>
      <p class="elder-eyebrow">{{ alert ? '请确认您的状况' : '实时守护中' }}</p>
      <h1>{{ alert ? (alert.kind === 'fall' ? '检测到疑似跌倒' : '当前风险较高') : '目前很安全' }}</h1>
      <p class="elder-description">{{ alert?.message || '请保持通道畅通，感到不稳时先坐下。' }}</p>
      <p v-if="remainingSeconds !== null && alert?.status === 'pending'" class="countdown">请在 <strong>{{ remainingSeconds }}</strong> 秒内响应</p>
      <div class="elder-actions">
        <button class="elder-button okay" :disabled="!alert || responding" @click="respond('safe')">我没事</button>
        <button class="elder-button help" :disabled="!alert || responding" @click="respond('help')">需要帮助</button>
      </div>
      <div class="elder-contact"><Phone />紧急联系人会收到站内与邮件通知</div>
    </main>
    <footer>风险结果仅用于安全辅助；紧急情况下请立即拨打当地急救电话。</footer>

    <el-dialog v-model="checkinOpen" title="今日身体状况" width="min(92vw, 560px)">
      <el-form label-width="130px"><el-form-item v-for="field in fields" :key="field.key" :label="field.label"><el-slider v-model="checkin[field.key]" :min="0" :max="5" show-input /></el-form-item><el-form-item label="近期调整用药"><el-switch v-model="checkin.medicationChanged" /></el-form-item><el-form-item label="所在场景"><el-select v-model="checkin.scene"><el-option label="客厅" value="客厅" /><el-option label="卧室" value="卧室" /><el-option label="卫生间" value="卫生间" /></el-select></el-form-item></el-form>
      <template #footer><el-button size="large" @click="checkinOpen = false">取消</el-button><el-button size="large" type="primary" @click="saveCheckin">保存问询</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Bell, FirstAidKit, Microphone, Phone } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import type { Result } from '../api/types'
import { useAuthStore } from '../stores/auth'
import request from '../utils/request'

interface Alert { alertId: string; kind: string; status: string; message: string; responseDeadline: string | null }

const POLL_MS = 3000
const auth = useAuthStore()
const alert = ref<Alert | null>(null)
const loading = ref(true)
const responding = ref(false)
const nowMs = ref(Date.now())
const checkinOpen = ref(false)
const previousAlertId = ref<string | null>(null)
const checkin = reactive<Record<'dizziness' | 'fatigue' | 'sleepQuality' | 'pain', number> & { medicationChanged: boolean; scene: string }>({ dizziness: 0, fatigue: 0, sleepQuality: 5, pain: 0, medicationChanged: false, scene: '客厅' })
const fields = [{ key: 'dizziness', label: '头晕（0-5）' }, { key: 'fatigue', label: '乏力（0-5）' }, { key: 'sleepQuality', label: '睡眠质量（0-5）' }, { key: 'pain', label: '疼痛（0-5）' }] as const
let pollTimer: number | undefined
let clockTimer: number | undefined
const remainingSeconds = computed(() => {
  if (!alert.value?.responseDeadline) return null
  return Math.max(0, Math.ceil((new Date(alert.value.responseDeadline).getTime() - nowMs.value) / 1000))
})

async function load(): Promise<void> {
  try {
    const response = await request.get<Result<Alert[]>>('/alerts', { params: { status: 'pending,confirmed,processing' }, headers: { 'X-Silent-Error': '1' } })
    const next = response.data.data[0] || null
    alert.value = next
    if (next && next.alertId !== previousAlertId.value) {
      previousAlertId.value = next.alertId
      speak()
    }
  } finally { loading.value = false }
}

async function respond(action: 'safe' | 'help'): Promise<void> {
  if (!alert.value) return
  responding.value = true
  try {
    await request.patch(`/alerts/${alert.value.alertId}`, { action })
    ElMessage.success(action === 'safe' ? '已记录您目前安全' : '已通知家属，请先坐稳')
    await load()
    speak(action === 'help' ? '已通知家属，请保持坐稳。' : '当前状态已记录，请慢慢起身。')
  } finally { responding.value = false }
}

function speak(text?: string): void {
  const message = text || alert.value?.message || '当前状态平稳，请起身时慢一些。'
  window.speechSynthesis?.cancel()
  window.speechSynthesis?.speak(new SpeechSynthesisUtterance(message))
}

async function saveCheckin(): Promise<void> {
  const elderId = auth.user.value?.elderId
  if (!elderId) { ElMessage.error('老人账号尚未绑定档案'); return }
  await request.post(`/elders/${elderId}/daily-checkins`, checkin)
  checkinOpen.value = false
  ElMessage.success('今日问询已保存并完成风险更新')
}

onMounted(async () => {
  await load()
  pollTimer = window.setInterval(load, POLL_MS)
  clockTimer = window.setInterval(() => { nowMs.value = Date.now() }, 1000)
})
onBeforeUnmount(() => { window.clearInterval(pollTimer); window.clearInterval(clockTimer) })
</script>

<style scoped>
.elder-screen {
  min-height: 100vh;
  padding: clamp(18px, 4vw, 54px);
  background: #f2f8fc;
  color: #163c56;
  display: flex;
  flex-direction: column;
}
.elder-screen.help { background: #fff7f5; }
header {
  width: min(100%, 1120px);
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.elder-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #0b496d;
  font-size: clamp(22px, 3vw, 32px);
  font-weight: 800;
}
.elder-brand :deep(svg) { width: 38px; height: 38px; color: #0a7bb5; }
.button {
  min-height: 48px;
  padding: 0 18px;
  border: 1px solid #82a8bd;
  border-radius: 9px;
  background: #fff;
  color: #164b6a;
  font: inherit;
  font-size: 17px;
  font-weight: 700;
  cursor: pointer;
}
.button:hover, .button:focus-visible { border-color: #087db7; outline: 3px solid #b8e3f7; }
.button :deep(svg) { width: 19px; height: 19px; margin-right: 6px; vertical-align: -3px; }
main {
  width: min(100%, 860px);
  margin: auto;
  padding: clamp(32px, 7vw, 76px) 24px;
  text-align: center;
}
.elder-status-icon {
  width: clamp(76px, 12vw, 112px);
  height: clamp(76px, 12vw, 112px);
  margin: 0 auto 22px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #dff3fb;
  color: #087db7;
}
.help .elder-status-icon { background: #fee2e2; color: #c52020; }
.elder-status-icon :deep(svg) { width: 56%; height: 56%; }
.elder-eyebrow { margin: 0 0 8px; color: #087db7; font-size: clamp(18px, 2.5vw, 25px); font-weight: 700; }
.help .elder-eyebrow { color: #b91c1c; }
h1 { margin: 0; color: #113952; font-size: clamp(38px, 6vw, 68px); line-height: 1.18; }
.elder-description { max-width: 680px; margin: 22px auto; color: #43697e; font-size: clamp(20px, 3vw, 29px); line-height: 1.6; }
.elder-actions { display: flex; justify-content: center; gap: 18px; margin-top: 30px; }
.elder-button {
  min-width: min(42vw, 230px);
  min-height: 72px;
  border: 0;
  border-radius: 13px;
  color: #fff;
  font: inherit;
  font-size: clamp(24px, 3vw, 32px);
  font-weight: 800;
  cursor: pointer;
}
.elder-button.okay { background: #138a57; }
.elder-button.help { background: #d73333; }
.elder-button:disabled { opacity: .45; cursor: not-allowed; }
.elder-button:not(:disabled):focus-visible { outline: 4px solid #153e56; outline-offset: 4px; }
.elder-contact { margin-top: 28px; color: #59798b; font-size: clamp(17px, 2.4vw, 23px); }
.elder-contact :deep(svg) { width: 1.1em; height: 1.1em; margin-right: 7px; vertical-align: -2px; }
footer { width: min(100%, 1120px); margin: 0 auto; color: #5d7a8c; font-size: 16px; text-align: center; }
.countdown { font-size: clamp(22px, 4vw, 38px); color: #b91c1c; }
.countdown strong { font-size: 1.35em; }
header > div:last-child { display: flex; gap: 10px; }
@media (max-width: 640px) {
  .elder-screen { padding: 18px 14px; }
  header { align-items: flex-start; }
  header > div:last-child { flex-direction: column; }
  .button { min-height: 44px; font-size: 15px; }
  main { padding: 42px 4px; }
  .elder-actions { gap: 10px; }
  .elder-button { min-width: 0; flex: 1; min-height: 64px; }
}
</style>
