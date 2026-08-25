<template>
  <div class="page">
    <div class="page-heading"><div><p class="eyebrow">安全运营概览</p><h1>安全总览</h1><p class="muted">真实风险趋势、场景统计、行为事件及待处理告警。</p></div><el-button type="primary" @click="load">刷新数据</el-button></div>
    <el-row :gutter="16" class="metric-row"><el-col v-for="metric in metrics" :key="metric.label" :xs="12" :lg="6"><el-card shadow="never"><el-statistic :title="metric.label" :value="metric.value" /></el-card></el-col></el-row>
    <el-row :gutter="16">
      <el-col :lg="16">
        <el-card shadow="never" v-loading="loading"><template #header><b>最近风险趋势</b></template><el-empty v-if="!data.riskTrend.length" description="暂无评估记录" /><svg v-else class="trend" viewBox="0 0 600 180" role="img" aria-label="风险分数趋势"><line v-for="value in [0, 20, 40, 60, 80, 100]" :key="value" x1="42" x2="590" :y1="165-value*1.4" :y2="165-value*1.4" stroke="#dbe7ee" /><polyline :points="trendPoints" fill="none" stroke="#087db7" stroke-width="4" stroke-linejoin="round" /><circle v-for="(item,index) in data.riskTrend" :key="item.assessmentId" :cx="pointX(index)" :cy="pointY(item.score)" r="4" :fill="item.level==='high'?'#dc2626':item.level==='medium'?'#d97706':'#16a34a'" /></svg></el-card>
      </el-col>
      <el-col :lg="8"><el-card shadow="never"><template #header><b>场景统计</b></template><el-table :data="sceneRows" size="small"><el-table-column prop="scene" label="场景" /><el-table-column prop="count" label="次数" /><el-table-column label="平均分"><template #default="{ row }">{{ row.averageScore ?? '-' }}</template></el-table-column></el-table></el-card></el-col>
    </el-row>
    <el-row :gutter="16" class="mt-20">
      <el-col :lg="15"><el-card shadow="never"><template #header><div class="card-title"><b>对象风险</b><RouterLink to="/elders">查看全部</RouterLink></div></template><el-table :data="data.elders" stripe><el-table-column prop="name" label="姓名" /><el-table-column label="授权"><template #default="{ row }"><el-tag :type="row.consentGranted?'success':'info'">{{ row.consentGranted?'已授权':'未授权' }}</el-tag></template></el-table-column><el-table-column label="风险"><template #default="{ row }">{{ row.latestRisk ? `${row.latestRisk.score} 分` : '暂无评估' }}</template></el-table-column><el-table-column label="主要原因" min-width="180"><template #default="{ row }">{{ row.latestRisk?.reasons?.[0] || '-' }}</template></el-table-column></el-table></el-card></el-col>
      <el-col :lg="9"><el-card shadow="never"><template #header><b>行为事件统计</b></template><el-empty v-if="!behaviorRows.length" description="暂无行为事件" /><div v-for="item in behaviorRows" :key="item.type" class="behavior-row"><span>{{ behaviorLabel(item.type) }}</span><el-tag type="warning">{{ item.count }} 次</el-tag></div></el-card></el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import type { Result } from '../api/types'
import request from '../utils/request'

interface Trend { assessmentId: string; score: number; level: string; scene: string; createdAt: string }
interface Elder { elderId: string; name: string; consentGranted: boolean; latestRisk: null | { score: number; reasons: string[] } }
interface DashboardData { elders: Elder[]; alerts: unknown[]; riskTrend: Trend[]; sceneStats: Record<string, { count: number; averageScore: number | null }>; behaviorEventCounts: Record<string, number>; summary: { elderCount: number; highRiskCount: number; mediumRiskCount: number; averageRiskScore: number | null } }
const emptyData = (): DashboardData => ({ elders: [], alerts: [], riskTrend: [], sceneStats: {}, behaviorEventCounts: {}, summary: { elderCount: 0, highRiskCount: 0, mediumRiskCount: 0, averageRiskScore: null } })
const data = ref<DashboardData>(emptyData())
const loading = ref(false)
const metrics = computed(() => [{ label: '关怀对象', value: data.value.summary.elderCount }, { label: '高风险对象', value: data.value.summary.highRiskCount }, { label: '中风险对象', value: data.value.summary.mediumRiskCount }, { label: '平均风险分', value: data.value.summary.averageRiskScore ?? 0 }])
const sceneRows = computed(() => ['客厅', '卧室', '卫生间'].map((scene) => ({ scene, ...(data.value.sceneStats[scene] || { count: 0, averageScore: null }) })))
const behaviorRows = computed(() => Object.entries(data.value.behaviorEventCounts).map(([type, count]) => ({ type, count })).sort((a, b) => b.count - a.count))
const trendPoints = computed(() => data.value.riskTrend.map((item, index) => `${pointX(index)},${pointY(item.score)}`).join(' '))
function pointX(index: number): number { const length = Math.max(1, data.value.riskTrend.length - 1); return 42 + index * (548 / length) }
function pointY(score: number): number { return 165 - Math.max(0, Math.min(100, score)) * 1.4 }
function behaviorLabel(type: string): string { return { trunk_instability: '躯干不稳', gait_variability: '步态变异', rapid_stand_after_sitting: '久坐快速起身', suspected_wall_support: '疑似扶墙', pacing: '徘徊', night_activity: '夜间活动' }[type] || type }
async function load(): Promise<void> { loading.value = true; try { data.value = (await request.get<Result<DashboardData>>('/dashboard')).data.data } finally { loading.value = false } }
onMounted(load)
</script>

<style scoped>
.trend { width: 100%; height: 220px; }
.behavior-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #edf3f7; }
</style>
