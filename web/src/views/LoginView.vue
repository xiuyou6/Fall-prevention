<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { FirstAidKit, Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore(); const router = useRouter(); const form = ref({ username: '', password: '' }); const loading = ref(false)
async function submit() { loading.value = true; try { const user = await auth.login(form.value.username, form.value.password); await router.replace(user.role === 'elder' ? '/elder-home' : '/dashboard') } finally { loading.value = false } }
</script>
<template><main class="login-page"><section class="login-aside"><div class="login-brand"><FirstAidKit /><strong>安步守护</strong></div><div><p>本地跌倒预防与告警系统</p><h1>守护每一步<br>安心每一天</h1><ul><li>本地视频与风险识别</li><li>异常事件闭环处置</li><li>家属授权与隐私保护</li></ul></div><small>风险结果仅作安全辅助提示，不构成医疗诊断。</small></section><section class="login-panel"><el-card shadow="never"><div class="login-title"><h2>欢迎登录</h2><p>使用系统账号进入管理工作台</p></div><el-form label-position="top" @submit.prevent="submit"><el-form-item label="账号"><el-input v-model="form.username" size="large" :prefix-icon="User" autocomplete="username" /></el-form-item><el-form-item label="密码"><el-input v-model="form.password" type="password" show-password size="large" :prefix-icon="Lock" autocomplete="current-password" /></el-form-item><el-button class="login-submit" native-type="submit" type="primary" size="large" :loading="loading">登录系统</el-button></el-form><div class="login-hint">三类账号均由系统管理员统一创建和管理</div></el-card></section></main></template>
