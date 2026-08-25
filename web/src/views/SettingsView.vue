<template>
  <div class="page">
    <div class="page-heading"><div><p class="eyebrow">系统运行与隐私</p><h1>系统诊断</h1><p class="muted">仅显示运行状态，不展示 SMTP 密码或其他敏感配置。</p></div><el-button type="primary" :loading="loading" @click="load">重新检测</el-button></div>
    <el-row :gutter="16">
      <el-col v-for="item in checks" :key="item.label" :xs="24" :sm="12" :lg="8"><el-card shadow="never" class="status-card"><span>{{ item.label }}</span><el-tag :type="item.ok ? 'success' : 'danger'">{{ item.text }}</el-tag></el-card></el-col>
    </el-row>
    <el-card v-if="status" shadow="never" class="mt-20"><template #header><b>运行参数</b></template><el-descriptions :column="2" border><el-descriptions-item label="数据库">{{ status.database }}</el-descriptions-item><el-descriptions-item label="时区">{{ status.timezone }}</el-descriptions-item><el-descriptions-item label="跌倒响应时间">{{ status.alertResponseSeconds }} 秒</el-descriptions-item><el-descriptions-item label="家属轮询建议">{{ status.alertPollSeconds }} 秒</el-descriptions-item><el-descriptions-item label="风险公式版本">{{ status.riskFormulaVersion }}</el-descriptions-item><el-descriptions-item label="视频来源">浏览器默认摄像头、本地视频上传</el-descriptions-item></el-descriptions></el-card>
    <el-alert class="mt-20" type="info" :closable="false" title="系统不接入萤石云、RTSP 或摄像头设备选择；视频和风险数据仅保存在本机。" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import type { Result } from '../api/types'
import request from '../utils/request'

interface SystemStatus { fallModelReady: boolean; poseModelReady: boolean; smtpConfigured: boolean; backgroundWorkerRunning: boolean; database: string; timezone: string; alertResponseSeconds: number; alertPollSeconds: number; riskFormulaVersion: string }
const status = ref<SystemStatus | null>(null)
const loading = ref(false)
const checks = computed(() => status.value ? [
  { label: 'YOLO 跌倒模型', ok: status.value.fallModelReady, text: status.value.fallModelReady ? '已就绪' : '模型缺失' },
  { label: 'MediaPipe 姿态模型', ok: status.value.poseModelReady, text: status.value.poseModelReady ? '已就绪' : '模型缺失' },
  { label: '后台任务', ok: status.value.backgroundWorkerRunning, text: status.value.backgroundWorkerRunning ? '运行中' : '未运行' },
  { label: '邮件通知', ok: status.value.smtpConfigured, text: status.value.smtpConfigured ? '已配置' : '未配置 SMTP' },
] : [])
async function load(): Promise<void> { loading.value = true; try { status.value = (await request.get<Result<SystemStatus>>('/admin/system-status')).data.data } finally { loading.value = false } }
onMounted(load)
</script>

<style scoped>
.status-card { margin-bottom: 16px; }
.status-card :deep(.el-card__body) { display: flex; justify-content: space-between; align-items: center; }
</style>
