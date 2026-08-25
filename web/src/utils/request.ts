import axios from 'axios'
import { ElMessage } from 'element-plus'
import type { Result } from '../api/types'

const service = axios.create({ baseURL: '/api', timeout: 10_000, withCredentials: true })

service.interceptors.request.use((config) => {
  const csrfToken = sessionStorage.getItem('csrfToken')
  if (csrfToken) config.headers.set('X-CSRFToken', csrfToken)
  return config
})

service.interceptors.response.use(
  (response) => {
    const result = response.data as Result<unknown>
    if (result.code === '200') return response
    if (response.config.headers?.['X-Silent-Error'] !== '1') ElMessage.error(result.message || '请求未完成')
    return Promise.reject(new Error(result.message))
  },
  (error: unknown) => {
    const silent = axios.isAxiosError(error) && error.config?.headers?.['X-Silent-Error'] === '1'
    const message = axios.isAxiosError(error)
      ? (error.response?.data as Result<unknown> | undefined)?.message || error.message
      : '网络请求失败'
    if (!silent) ElMessage.error(message)
    if (axios.isAxiosError(error) && error.response?.status === 401 && window.location.pathname !== '/login') {
      sessionStorage.removeItem('csrfToken')
      window.location.assign('/login')
    }
    return Promise.reject(error)
  },
)

export default service
