import { computed, ref } from 'vue'
import request from '../utils/request'
import type { Result } from '../api/types'

export type UserRole = 'admin' | 'family' | 'elder'
export interface CurrentUser { userId: string; username: string; displayName: string; role: UserRole; elderId: string | null }
const user = ref<CurrentUser | null>(null)
const ready = ref(false)
export function useAuthStore() {
  const isAuthenticated = computed(() => user.value !== null)
  async function load(): Promise<void> {
    try {
      const response = await request.get<Result<{ user: CurrentUser; csrfToken: string }>>('/auth/me', { headers: { 'X-Silent-Error': '1' } })
      user.value = response.data.data.user
      sessionStorage.setItem('csrfToken', response.data.data.csrfToken)
    } catch { user.value = null } finally { ready.value = true }
  }
  async function login(username: string, password: string): Promise<CurrentUser> {
    const response = await request.post<Result<{ user: CurrentUser; csrfToken: string }>>('/auth/login', { username, password })
    user.value = response.data.data.user
    sessionStorage.setItem('csrfToken', response.data.data.csrfToken)
    return user.value
  }
  async function logout(): Promise<void> { await request.post('/auth/logout'); sessionStorage.removeItem('csrfToken'); user.value = null }
  return { user, ready, isAuthenticated, load, login, logout }
}
