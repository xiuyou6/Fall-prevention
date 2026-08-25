<template>
  <div class="page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">本地视频任务</p>
        <h1>本地视频分析</h1>
        <p class="muted">上传的视频在本机逐帧分析；左侧画面与右侧风险数据同步展示。</p>
      </div>
      <el-button @click="backToElders">返回关怀对象</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :lg="16">
        <el-card shadow="never">
          <video
            v-if="!loadError && !useDecodedFrames"
            ref="video"
            :src="previewUrl"
            controls
            autoplay
            muted
            playsinline
            class="monitor-video"
            @loadeddata="nativePreviewReady"
            @timeupdate="syncNativeTime"
            @error="useFrameFallback"
          />
          <section v-else-if="!loadError" class="frame-player" aria-label="兼容视频播放">
            <img :src="frameUrl" alt="视频解码画面" class="monitor-video frame-image" />
            <div class="frame-controls">
              <el-button type="primary" @click="toggleFramePlayback">{{ framePlaying ? '暂停播放' : '播放视频' }}</el-button>
              <input :value="playbackTime" type="range" min="0" :max="safeDuration" step="0.05" aria-label="视频播放进度" @input="seekFrame" />
              <span>{{ playbackTimeText }} / {{ durationText }}</span>
            </div>
            <p class="frame-hint">当前浏览器不支持原视频编码，已切换为本地逐帧兼容播放。</p>
          </section>
          <el-result v-else icon="error" title="视频无法加载" :sub-title="loadError" />
        </el-card>
      </el-col>
      <el-col :lg="8">
        <el-card shadow="never" v-loading="loading">
          <el-descriptions :column="1" title="分析状态">
            <el-descriptions-item label="任务状态">
              <el-tag :type="statusType">{{ statusText }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="场景">{{ job?.scene || '-' }}</el-descriptions-item>
            <el-descriptions-item label="提交状态">{{ submissionText }}</el-descriptions-item>
            <el-descriptions-item label="YOLO 置信度">{{ confidenceText }}</el-descriptions-item>
            <el-descriptions-item label="风险结果">{{ riskText }}</el-descriptions-item>
            <el-descriptions-item label="主要原因">{{ reasonsText }}</el-descriptions-item>
            <el-descriptions-item label="行为数据">{{ behaviorText }}</el-descriptions-item>
          </el-descriptions>
          <el-alert v-if="job?.status === 'failed'" class="mt-20" type="error" :closable="false" :title="`分析失败：${job.errorMessage || '未知错误'}`" />
          <el-alert v-else-if="!finished" class="mt-20" type="info" :closable="false" title="正在本机逐帧分析，完成后将显示风险评分与行为数据。" />
          <el-button v-if="job?.alertId" class="mt-20" type="danger" @click="goToAlert">查看关联告警</el-button>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { Result } from '../api/types'
import request from '../utils/request'

interface DataQuality { sufficient?: boolean; reason?: string; gait?: string }
interface Assessment {
  score: number | null
  level: string
  reasons: string[]
  features: { dataQuality?: DataQuality; behaviorRaw?: Record<string, number> }
}
interface VideoJob {
  videoJobId: string
  elderId: string
  scene: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  errorMessage: string | null
  totalFrames: number
  progressFrames: number
  durationSeconds: number | null
  currentConfidence: number | null
  frameMetrics: FrameMetric[]
  assessment: Assessment | null
  alertId: string | null
}
interface FrameMetric { time: number; confidence: number; fall: boolean }

const POLL_INTERVAL_MS = 2_000
const FRAME_INTERVAL_MS = 250
const NATIVE_PREVIEW_TIMEOUT_MS = 7_000
const route = useRoute()
const router = useRouter()
const elderId = String(route.params.elderId)
const jobId = String(route.params.jobId)
const job = ref<VideoJob | null>(null)
const loading = ref(true)
const loadError = ref('')
const video = ref<HTMLVideoElement>()
const useDecodedFrames = ref(false)
const framePlaying = ref(false)
const playbackTime = ref(0)
let pollTimer: number | undefined
let frameTimer: number | undefined
let previewTimer: number | undefined

const previewUrl = computed(() => `/api/video-jobs/${encodeURIComponent(jobId)}/preview`)
const frameUrl = computed(() => `/api/video-jobs/${encodeURIComponent(jobId)}/frame?time=${playbackTime.value.toFixed(3)}&v=${Date.now()}`)
const safeDuration = computed(() => Math.max(job.value?.durationSeconds || 0, 0.05))
const durationText = computed(() => formatSeconds(job.value?.durationSeconds || 0))
const playbackTimeText = computed(() => formatSeconds(playbackTime.value))
const finished = computed(() => ['succeeded', 'failed'].includes(job.value?.status || ''))
const statusText = computed(() => ({ pending: '等待分析', running: '分析中', succeeded: '分析完成', failed: '分析失败' }[job.value?.status || 'pending']))
const statusType = computed<'info' | 'warning' | 'success' | 'danger'>(() => {
  const types: Record<VideoJob['status'], 'info' | 'warning' | 'success' | 'danger'> = { pending: 'info', running: 'warning', succeeded: 'success', failed: 'danger' }
  return types[job.value?.status || 'pending']
})
const submissionText = computed(() => job.value?.status === 'running' ? '后台正在逐帧分析' : job.value?.status === 'pending' ? '视频已提交，等待后台任务' : job.value?.status === 'succeeded' ? '分析结果已保存' : job.value?.status === 'failed' ? '任务未完成' : '正在加载任务')
const currentMetric = computed(() => {
  const metrics = job.value?.frameMetrics || []
  if (!metrics.length) return null
  return metrics.reduce((closest, metric) => Math.abs(metric.time - playbackTime.value) < Math.abs(closest.time - playbackTime.value) ? metric : closest)
})
const confidenceText = computed(() => {
  if (currentMetric.value) return `${(currentMetric.value.confidence * 100).toFixed(1)}%${currentMetric.value.fall ? ' · 疑似倒地帧' : ''}`
  if (job.value?.currentConfidence !== null && job.value?.currentConfidence !== undefined) return `${(job.value.currentConfidence * 100).toFixed(1)}% · 正在分析`
  return '等待逐帧模型结果'
})
const riskText = computed(() => job.value?.assessment ? `${riskLevelText(job.value.assessment.level)} · ${job.value.assessment.score ?? '-'} 分` : '等待分析结果')
const reasonsText = computed(() => job.value?.assessment?.reasons?.join('；') || '-')
const behaviorText = computed(() => {
  const assessment = job.value?.assessment
  const quality = assessment?.features.dataQuality
  if (!quality?.sufficient) return quality?.reason || '数据不足，需人工确认'
  const values = assessment?.features.behaviorRaw || {}
  const active = Object.entries(values).filter(([, value]) => value > 0).map(([key, value]) => `${behaviorLabel(key)} ${value.toFixed(1)}`)
  return active.join('；') || quality.gait || '未发现达到阈值的行为风险'
})

function riskLevelText(level: string): string { return { high: '高风险', medium: '中风险', low: '低风险' }[level] || level }
function behaviorLabel(key: string): string { return { instability: '姿态不稳', gait: '步态异常', sit_stand: '突然起身', pacing: '徘徊', wall_support: '疑似扶墙', night: '夜间活动' }[key] || key }
function formatSeconds(value: number): string { const whole = Math.max(0, Math.floor(value)); return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}` }
function syncNativeTime(): void { playbackTime.value = video.value?.currentTime || 0 }
function nativePreviewReady(): void { window.clearTimeout(previewTimer) }
function useFrameFallback(): void { window.clearTimeout(previewTimer); useDecodedFrames.value = true }
function toggleFramePlayback(): void { framePlaying.value = !framePlaying.value; scheduleFrame() }
function seekFrame(event: Event): void { playbackTime.value = Number((event.target as HTMLInputElement).value) || 0 }
function scheduleFrame(): void {
  window.clearInterval(frameTimer)
  if (!framePlaying.value) return
  frameTimer = window.setInterval(() => {
    const next = playbackTime.value + FRAME_INTERVAL_MS / 1_000
    if (next >= safeDuration.value) { playbackTime.value = safeDuration.value; framePlaying.value = false; scheduleFrame(); return }
    playbackTime.value = next
  }, FRAME_INTERVAL_MS)
}

async function loadJob(): Promise<void> {
  try {
    const response = await request.get<Result<VideoJob>>(`/video-jobs/${jobId}`, { headers: { 'X-Silent-Error': '1' } })
    job.value = response.data.data
    if (job.value.elderId !== elderId) {
      loadError.value = '任务与当前关怀对象不匹配'
      clearPolling()
      return
    }
    if (finished.value) clearPolling()
  } catch {
    loadError.value = '无法读取分析任务，请确认您仍拥有该关怀对象的授权。'
    clearPolling()
  } finally {
    loading.value = false
  }
}
function startPolling(): void { clearPolling(); pollTimer = window.setInterval(loadJob, POLL_INTERVAL_MS) }
function clearPolling(): void { window.clearInterval(pollTimer); pollTimer = undefined }
function backToElders(): void { router.push('/elders') }
function goToAlert(): void { router.push('/alerts') }

onMounted(async () => {
  await loadJob()
  if (!finished.value && !loadError.value) startPolling()
  previewTimer = window.setTimeout(useFrameFallback, NATIVE_PREVIEW_TIMEOUT_MS)
})
onBeforeUnmount(() => { clearPolling(); window.clearInterval(frameTimer); window.clearTimeout(previewTimer) })
</script>

<style scoped>
.monitor-video { display: block; width: 100%; min-height: 360px; max-height: 70vh; background: #101820; object-fit: contain; }
.frame-player { background: #101820; }
.frame-image { margin: 0 auto; }
.frame-controls { min-height: 58px; padding: 10px; display: flex; align-items: center; gap: 12px; color: #fff; }
.frame-controls input { flex: 1; }
.frame-hint { margin: 0; padding: 0 12px 12px; color: #c4d8e8; font-size: 13px; }
</style>
