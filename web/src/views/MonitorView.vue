<template>
  <div class="page">
    <div class="page-heading"><div><p class="eyebrow">本地默认摄像头</p><h1>实时安全监测</h1><p class="muted">不枚举设备；使用浏览器和操作系统选择的默认摄像头。</p></div><div><el-select v-model="scene" :disabled="running" style="width: 110px"><el-option label="客厅" value="客厅" /><el-option label="卧室" value="卧室" /><el-option label="卫生间" value="卫生间" /></el-select><el-button v-if="!running" type="primary" class="ml-10" @click="start">启动摄像头</el-button><el-button v-else type="danger" class="ml-10" @click="stop">停止监测</el-button></div></div>
    <el-row :gutter="16"><el-col :lg="16"><el-card shadow="never"><video ref="video" autoplay playsinline muted class="monitor-video" /><canvas ref="canvas" class="hidden-canvas" /></el-card></el-col><el-col :lg="8"><el-card shadow="never"><el-descriptions :column="1" title="实时状态"><el-descriptions-item label="会话"><el-tag :type="running ? 'success' : 'info'">{{ running ? '监测中' : '未启动' }}</el-tag></el-descriptions-item><el-descriptions-item label="场景">{{ scene }}</el-descriptions-item><el-descriptions-item label="提交状态">{{ submitState }}</el-descriptions-item><el-descriptions-item label="YOLO 置信度">{{ confidence }}</el-descriptions-item><el-descriptions-item label="风险结果">{{ riskText }}</el-descriptions-item><el-descriptions-item label="主要原因">{{ reasons.join('；') || '-' }}</el-descriptions-item><el-descriptions-item label="行为数据">{{ dataQuality }}</el-descriptions-item></el-descriptions><el-alert class="mt-20" type="warning" :closable="false" title="模型首次加载及 CPU 推理可能需要数十秒；请求串行发送，不会堆积。" /></el-card></el-col></el-row>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

import type { Result } from '../api/types'
import request from '../utils/request'

interface FrameResult { confidence: number; fall: boolean; risk: { level: string; score: number; reasons: string[]; features: { dataQuality?: { sufficient?: boolean; reason?: string; gait?: string } } } }
const route = useRoute()
const elderId = String(route.params.elderId)
const video = ref<HTMLVideoElement>()
const canvas = ref<HTMLCanvasElement>()
const running = ref(false)
const sessionId = ref('')
const scene = ref('客厅')
const riskText = ref('等待启动')
const reasons = ref<string[]>([])
const dataQuality = ref('等待姿态数据')
const confidence = ref(0)
const submitState = ref('未提交')
let stream: MediaStream | null = null
let nextTimer: number | undefined
let sending = false

async function start(): Promise<void> {
  try {
    const response = await request.post<Result<{ monitorSessionId: string }>>(`/elders/${elderId}/monitor-sessions`, { scene: scene.value })
    sessionId.value = response.data.data.monitorSessionId
    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
    if (video.value) video.value.srcObject = stream
    running.value = true
    riskText.value = '摄像头已启动，等待首帧分析'
    schedule(300)
  } catch { ElMessage.error('无法启动摄像头，请检查浏览器权限和隐私授权') }
}

function schedule(delay: number): void { if (running.value) nextTimer = window.setTimeout(sendFrame, delay) }

async function sendFrame(): Promise<void> {
  if (sending || !video.value || !canvas.value || video.value.readyState < 2 || !sessionId.value) { schedule(500); return }
  sending = true
  submitState.value = '正在本地分析…'
  canvas.value.width = video.value.videoWidth
  canvas.value.height = video.value.videoHeight
  canvas.value.getContext('2d')?.drawImage(video.value, 0, 0)
  canvas.value.toBlob(async (blob) => {
    try {
      if (!blob) return
      const body = new FormData()
      body.append('frame', blob, 'frame.jpg')
      const response = await request.post<Result<FrameResult>>(`/monitor-sessions/${sessionId.value}/frames`, body, { timeout: 60_000, headers: { 'X-Silent-Error': '1' } })
      const result = response.data.data
      confidence.value = result.confidence
      riskText.value = result.fall ? '疑似跌倒，请立即确认' : `${result.risk.level} · ${result.risk.score} 分`
      reasons.value = result.risk.reasons
      const quality = result.risk.features.dataQuality
      dataQuality.value = quality?.sufficient ? quality.gait || '有效' : quality?.reason || '数据不足'
      submitState.value = '上一帧分析完成'
      if (result.fall) window.speechSynthesis?.speak(new SpeechSynthesisUtterance('检测到疑似跌倒，请先坐稳并确认状况。'))
      else if (result.risk.level === 'high') window.speechSynthesis?.speak(new SpeechSynthesisUtterance(result.risk.reasons[0] || '当前跌倒风险较高，请先坐稳。'))
    } catch { submitState.value = '本帧分析超时，将自动重试' }
    finally { sending = false; schedule(800) }
  }, 'image/jpeg', 0.62)
}

async function stop(): Promise<void> {
  window.clearTimeout(nextTimer)
  running.value = false
  stream?.getTracks().forEach((track) => track.stop())
  if (sessionId.value) {
    try { await request.post(`/monitor-sessions/${sessionId.value}/stop`, {}, { timeout: 15_000 }) } catch { /* 页面卸载时允许静默失败 */ }
  }
  sessionId.value = ''
  submitState.value = '已停止'
}

onBeforeUnmount(stop)
</script>
