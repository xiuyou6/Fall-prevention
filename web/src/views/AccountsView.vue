<template>
  <div class="page">
    <div class="page-heading">
      <div><p class="eyebrow">三角色账号</p><h1>账号管理</h1><p class="muted">管理员统一创建管理员、家属和老人账号。</p></div>
      <el-button type="primary" @click="openCreate">新增账号</el-button>
    </div>
    <el-card shadow="never">
      <el-table :data="users" v-loading="loading" stripe>
        <el-table-column prop="username" label="登录账号" />
        <el-table-column prop="displayName" label="姓名" />
        <el-table-column label="角色"><template #default="{ row }"><el-tag :type="roleTag(row.role)">{{ roleLabel(row.role) }}</el-tag></template></el-table-column>
        <el-table-column label="绑定老人"><template #default="{ row }">{{ elderName(row.elderId) }}</template></el-table-column>
        <el-table-column label="状态"><template #default="{ row }"><el-tag :type="row.isActive ? 'success' : 'info'">{{ row.isActive ? '正常' : '已停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button link type="primary" @click="toggle(row)">{{ row.isActive ? '停用' : '启用' }}</el-button>
            <el-button link type="primary" @click="resetPassword(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="createOpen" title="新增系统账号" width="500px">
      <el-form label-width="95px">
        <el-form-item label="账号角色"><el-select v-model="form.role" class="w-full"><el-option label="管理员" value="admin" /><el-option label="家属" value="family" /><el-option label="老人" value="elder" /></el-select></el-form-item>
        <el-form-item v-if="form.role === 'elder'" label="绑定老人"><el-select v-model="form.elderId" class="w-full"><el-option v-for="elder in availableElders" :key="elder.elderId" :label="elder.name" :value="elder.elderId" /></el-select></el-form-item>
        <el-form-item label="登录账号"><el-input v-model="form.username" autocomplete="off" /></el-form-item>
        <el-form-item label="显示姓名"><el-input v-model="form.displayName" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /><small class="muted">至少 8 位</small></el-form-item>
      </el-form>
      <template #footer><el-button @click="createOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="createAccount">创建账号</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import type { Result } from '../api/types'
import type { UserRole } from '../stores/auth'
import request from '../utils/request'

interface Account { userId: string; username: string; displayName: string; role: UserRole; isActive: boolean; elderId: string | null }
interface ElderOption { elderId: string; name: string }

const users = ref<Account[]>([])
const elders = ref<ElderOption[]>([])
const loading = ref(false)
const saving = ref(false)
const createOpen = ref(false)
const form = reactive({ username: '', displayName: '', password: '', role: 'family' as UserRole, elderId: '' })
const availableElders = computed(() => elders.value.filter((elder) => !users.value.some((user) => user.role === 'elder' && user.elderId === elder.elderId)))

function roleLabel(role: UserRole): string { return { admin: '管理员', family: '家属', elder: '老人' }[role] }
function roleTag(role: UserRole): 'danger' | 'warning' | 'success' { return role === 'admin' ? 'danger' : role === 'family' ? 'warning' : 'success' }
function elderName(elderId: string | null): string { return elders.value.find((item) => item.elderId === elderId)?.name || '-' }
function openCreate(): void { Object.assign(form, { username: '', displayName: '', password: '', role: 'family', elderId: '' }); createOpen.value = true }

async function load(): Promise<void> {
  loading.value = true
  try {
    const [usersResponse, eldersResponse] = await Promise.all([
      request.get<Result<Account[]>>('/admin/users'),
      request.get<Result<ElderOption[]>>('/elders'),
    ])
    users.value = usersResponse.data.data
    elders.value = eldersResponse.data.data
  } finally { loading.value = false }
}

async function createAccount(): Promise<void> {
  if (form.username.trim().length < 3 || !form.displayName.trim() || form.password.length < 8) {
    ElMessage.warning('请填写完整信息，密码至少 8 位')
    return
  }
  if (form.role === 'elder' && !form.elderId) { ElMessage.warning('老人账号必须绑定老人档案'); return }
  saving.value = true
  try {
    await request.post('/admin/users', form)
    createOpen.value = false
    ElMessage.success('账号已创建')
    await load()
  } finally { saving.value = false }
}

async function toggle(item: Account): Promise<void> {
  await request.patch(`/admin/users/${item.userId}`, { isActive: !item.isActive })
  item.isActive = !item.isActive
  ElMessage.success(item.isActive ? '账号已启用' : '账号已停用')
}

async function resetPassword(item: Account): Promise<void> {
  const { value } = await ElMessageBox.prompt('请输入至少 8 位的新密码', `重置 ${item.displayName} 的密码`, { inputType: 'password', inputPattern: /^.{8,}$/, inputErrorMessage: '密码至少 8 位' })
  await request.patch(`/admin/users/${item.userId}`, { password: value })
  ElMessage.success('密码已重置')
}

onMounted(load)
</script>

<style scoped>
small { display: block; margin-top: 5px; }
</style>
