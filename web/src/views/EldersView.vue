<template>
  <div class="page">
    <div class="page-heading">
      <div><p class="eyebrow">档案与风险管理</p><h1>{{ isAdmin ? '关怀对象' : '我的家人' }}</h1><p class="muted">维护联系人、环境、每日问询及本地视频分析。</p></div>
      <el-button v-if="isAdmin" type="primary" @click="openProfile()">新增老人档案</el-button>
    </div>
    <el-card shadow="never">
      <el-table :data="elders" v-loading="loading" stripe>
        <el-table-column label="姓名" min-width="130"><template #default="{ row }"><div class="table-person"><el-avatar>{{ row.name.slice(0, 1) }}</el-avatar><b>{{ row.name }}</b></div></template></el-table-column>
        <el-table-column label="年龄" width="90"><template #default="{ row }">{{ age(row.birthYear) }}</template></el-table-column>
        <el-table-column label="行动能力"><template #default="{ row }">{{ mobilityLabel(row.mobilityLevel) }}</template></el-table-column>
        <el-table-column label="隐私授权"><template #default="{ row }"><el-tag :type="row.consentGranted ? 'success' : 'info'">{{ row.consentGranted ? '已授权' : '未授权' }}</el-tag></template></el-table-column>
        <el-table-column label="最新风险" min-width="230"><template #default="{ row }"><el-tag :type="riskTag(row)">{{ riskText(row) }}</el-tag><span class="risk-reason">{{ row.latestRisk?.reasons?.[0] || '暂无评估' }}</span></template></el-table-column>
        <el-table-column label="操作" min-width="350" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openCare(row)">照护信息</el-button>
            <el-button link type="primary" @click="openEnvironment(row)">环境检查</el-button>
            <el-button link type="primary" @click="openUpload(row)">上传视频</el-button>
            <el-button link type="primary" @click="monitor(row)">摄像头</el-button>
            <el-dropdown trigger="click"><el-button link type="primary">导出报告</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item><a :href="`/api/elders/${row.elderId}/reports/risk.pdf`">PDF 风险报告</a></el-dropdown-item><el-dropdown-item><a :href="`/api/elders/${row.elderId}/reports/events.csv`">CSV 事件明细</a></el-dropdown-item></el-dropdown-menu></template></el-dropdown>
            <el-button v-if="isAdmin" link type="primary" @click="openProfile(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="profileOpen" :title="profile.elderId ? '编辑老人档案' : '新增老人档案'" width="520px">
      <el-form label-width="100px">
        <el-form-item label="姓名"><el-input v-model="profile.name" /></el-form-item>
        <el-form-item label="出生年份"><el-input-number v-model="profile.birthYear" :min="1900" :max="new Date().getFullYear()" /></el-form-item>
        <el-form-item label="行动能力"><el-select v-model="profile.mobilityLevel"><el-option label="可独立活动" value="independent" /><el-option label="行动受限" value="limited" /><el-option label="需要辅助" value="assisted" /></el-select></el-form-item>
        <el-form-item label="辅助器具"><el-input v-model="profile.assistiveDevice" /></el-form-item>
        <el-form-item label="既往跌倒"><el-switch v-model="profile.priorFalls" /></el-form-item>
        <el-form-item label="隐私授权"><el-switch v-model="profile.consentGranted" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="profileOpen = false">取消</el-button><el-button type="primary" @click="saveProfile">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="careOpen" :title="`${selected?.name || ''} · 照护信息`" width="760px">
      <el-tabs v-model="careTab">
        <el-tab-pane label="紧急联系人" name="contacts">
          <el-table :data="contacts" size="small"><el-table-column prop="name" label="姓名" /><el-table-column prop="email" label="邮箱" /><el-table-column prop="phone" label="电话" /><el-table-column prop="priority" label="优先级" width="80" /><el-table-column label="操作" width="80"><template #default="{ row }"><el-button link type="danger" @click="removeContact(row)">删除</el-button></template></el-table-column></el-table>
          <el-form :inline="true" class="mt-20"><el-form-item><el-input v-model="contactForm.name" placeholder="联系人姓名" /></el-form-item><el-form-item><el-input v-model="contactForm.email" placeholder="邮箱" /></el-form-item><el-form-item><el-input v-model="contactForm.phone" placeholder="电话" /></el-form-item><el-form-item><el-input-number v-model="contactForm.priority" :min="1" :max="99" /></el-form-item><el-form-item><el-button type="primary" @click="addContact">添加</el-button></el-form-item></el-form>
        </el-tab-pane>
        <el-tab-pane label="每日问询" name="checkin">
          <el-form label-width="130px"><el-form-item v-for="field in checkinFields" :key="field.key" :label="field.label"><el-slider v-model="checkin[field.key]" :min="0" :max="5" show-input /></el-form-item><el-form-item label="近期调整用药"><el-switch v-model="checkin.medicationChanged" /></el-form-item><el-form-item label="评估场景"><el-select v-model="checkin.scene"><el-option v-for="scene in scenes" :key="scene" :label="scene" :value="scene" /></el-select></el-form-item><el-form-item><el-button type="primary" @click="saveCheckin">保存并重新评分</el-button></el-form-item></el-form>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog v-model="environmentOpen" :title="`${selected?.name || ''} · 环境风险检查`" width="600px">
      <el-form label-width="80px"><el-form-item label="场景"><el-select v-model="environment.scene"><el-option v-for="scene in scenes" :key="scene" :label="scene" :value="scene" /></el-select></el-form-item><el-row><el-col v-for="field in environmentFields" :key="field.key" :span="12"><el-checkbox v-model="environment[field.key]">{{ field.label }}</el-checkbox></el-col></el-row><el-form-item label="备注" class="mt-20"><el-input v-model="environment.notes" type="textarea" /></el-form-item></el-form>
      <template #footer><el-button @click="environmentOpen = false">取消</el-button><el-button type="primary" @click="saveEnvironment">保存并重新评分</el-button></template>
    </el-dialog>

    <el-dialog v-model="uploadOpen" :title="`${selected?.name || ''} · 本地视频分析`" width="560px">
      <el-form label-width="90px"><el-form-item label="监测场景"><el-select v-model="uploadScene"><el-option v-for="scene in scenes" :key="scene" :label="scene" :value="scene" /></el-select></el-form-item><el-form-item label="视频文件"><input type="file" accept=".mp4,.avi,.mov,.mkv,video/*" @change="selectVideo" /></el-form-item></el-form>
      <template #footer><el-button @click="uploadOpen = false">取消</el-button><el-button type="primary" :loading="uploading" :disabled="!videoFile" @click="uploadVideo">上传并进入分析页</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import type { Result } from '../api/types'
import { useAuthStore } from '../stores/auth'
import request from '../utils/request'

type Scene = '客厅' | '卧室' | '卫生间'
interface Assessment { id?: string; score: number | null; level: string; reasons: string[] }
interface Elder { elderId: string; name: string; birthYear: number | null; priorFalls: boolean; consentGranted: boolean; mobilityLevel: string; assistiveDevice?: string | null; latestRisk: Assessment | null }
interface Contact { contactId: string; name: string; email: string; phone: string | null; priority: number }
const scenes: Scene[] = ['客厅', '卧室', '卫生间']
const auth = useAuthStore()
const router = useRouter()
const isAdmin = computed(() => auth.user.value?.role === 'admin')
const elders = ref<Elder[]>([])
const contacts = ref<Contact[]>([])
const selected = ref<Elder | null>(null)
const loading = ref(false)
const profileOpen = ref(false)
const careOpen = ref(false)
const careTab = ref('contacts')
const environmentOpen = ref(false)
const uploadOpen = ref(false)
const uploading = ref(false)
const videoFile = ref<File | null>(null)
const uploadScene = ref<Scene>('客厅')
const profile = reactive({ elderId: '', name: '', birthYear: 1950, mobilityLevel: 'independent', assistiveDevice: '', consentGranted: false, priorFalls: false })
const contactForm = reactive({ name: '', email: '', phone: '', priority: 1 })
const checkin = reactive<Record<'dizziness' | 'fatigue' | 'sleepQuality' | 'pain', number> & { medicationChanged: boolean; scene: Scene }>({ dizziness: 0, fatigue: 0, sleepQuality: 5, pain: 0, medicationChanged: false, scene: '客厅' })
const checkinFields = [{ key: 'dizziness', label: '头晕（0-5）' }, { key: 'fatigue', label: '乏力（0-5）' }, { key: 'sleepQuality', label: '睡眠质量（0-5）' }, { key: 'pain', label: '疼痛（0-5）' }] as const
const environment = reactive<Record<'wetFloor' | 'obstacles' | 'dimLight' | 'clutter' | 'exposedCables' | 'missingHandrail', boolean> & { scene: Scene; notes: string }>({ scene: '客厅', wetFloor: false, obstacles: false, dimLight: false, clutter: false, exposedCables: false, missingHandrail: false, notes: '' })
const environmentFields = [{ key: 'wetFloor', label: '地面湿滑' }, { key: 'obstacles', label: '通道有障碍' }, { key: 'dimLight', label: '照明不足' }, { key: 'clutter', label: '地面杂物' }, { key: 'exposedCables', label: '外露电线' }, { key: 'missingHandrail', label: '缺少扶手' }] as const
function age(year: number | null): string { return year ? `${new Date().getFullYear() - year} 岁` : '-' }
function mobilityLabel(value: string): string { return { independent: '独立活动', limited: '行动受限', assisted: '需要辅助' }[value] || value }
function riskTag(elder: Elder): 'danger' | 'warning' | 'success' | 'info' { return elder.latestRisk?.level === 'high' ? 'danger' : elder.latestRisk?.level === 'medium' ? 'warning' : elder.latestRisk ? 'success' : 'info' }
function riskText(elder: Elder): string { return elder.latestRisk ? `${{ high: '高风险', medium: '中风险', low: '低风险' }[elder.latestRisk.level] || elder.latestRisk.level} ${elder.latestRisk.score} 分` : '暂无评分' }

async function load(): Promise<void> { loading.value = true; try { elders.value = (await request.get<Result<Elder[]>>('/elders')).data.data } finally { loading.value = false } }
function openProfile(elder?: Elder): void { Object.assign(profile, elder ? { ...elder, birthYear: elder.birthYear || 1950, assistiveDevice: elder.assistiveDevice || '' } : { elderId: '', name: '', birthYear: 1950, mobilityLevel: 'independent', assistiveDevice: '', consentGranted: false, priorFalls: false }); profileOpen.value = true }
async function saveProfile(): Promise<void> { if (!profile.name.trim()) { ElMessage.warning('请填写姓名'); return } if (profile.elderId) await request.patch(`/elders/${profile.elderId}`, profile); else await request.post('/elders', profile); profileOpen.value = false; ElMessage.success('老人档案已保存'); await load() }
async function openCare(elder: Elder): Promise<void> { selected.value = elder; careOpen.value = true; careTab.value = 'contacts'; contacts.value = (await request.get<Result<Contact[]>>(`/elders/${elder.elderId}/contacts`)).data.data }
async function addContact(): Promise<void> { if (!selected.value) return; await request.post(`/elders/${selected.value.elderId}/contacts`, contactForm); Object.assign(contactForm, { name: '', email: '', phone: '', priority: 1 }); contacts.value = (await request.get<Result<Contact[]>>(`/elders/${selected.value.elderId}/contacts`)).data.data; ElMessage.success('联系人已添加') }
async function removeContact(contact: Contact): Promise<void> { if (!selected.value) return; await request.delete(`/elders/${selected.value.elderId}/contacts/${contact.contactId}`); contacts.value = contacts.value.filter((item) => item.contactId !== contact.contactId) }
async function saveCheckin(): Promise<void> { if (!selected.value) return; await request.post(`/elders/${selected.value.elderId}/daily-checkins`, checkin); ElMessage.success('每日问询已保存并重新评分'); await load() }
function openEnvironment(elder: Elder): void { selected.value = elder; Object.assign(environment, { scene: '客厅', wetFloor: false, obstacles: false, dimLight: false, clutter: false, exposedCables: false, missingHandrail: false, notes: '' }); environmentOpen.value = true }
async function saveEnvironment(): Promise<void> { if (!selected.value) return; await request.post(`/elders/${selected.value.elderId}/environment-checks`, environment); environmentOpen.value = false; ElMessage.success('环境检查已保存并重新评分'); await load() }
function monitor(elder: Elder): void { if (!elder.consentGranted) { ElMessage.warning('尚未取得隐私授权'); return } window.location.assign(`/elders/${elder.elderId}/monitor`) }
function openUpload(elder: Elder): void { if (!elder.consentGranted) { ElMessage.warning('尚未取得隐私授权'); return } selected.value = elder; videoFile.value = null; uploadOpen.value = true }
function selectVideo(event: Event): void { videoFile.value = (event.target as HTMLInputElement).files?.[0] || null }
async function uploadVideo(): Promise<void> { if (!selected.value || !videoFile.value) return; uploading.value = true; const body = new FormData(); body.append('scene', uploadScene.value); body.append('video', videoFile.value); try { const elderId = selected.value.elderId; const response = await request.post<Result<{ videoJobId: string; status: string }>>(`/elders/${elderId}/videos`, body, { timeout: 120_000 }); uploadOpen.value = false; videoFile.value = null; await router.push({ name: 'video-analysis', params: { elderId, jobId: response.data.data.videoJobId } }) } finally { uploading.value = false } }

onMounted(load)
</script>

<style scoped>
.risk-reason { margin-left: 7px; color: #819aa9; font-size: 12px; }
input[type='file'] { width: 100%; }
</style>
