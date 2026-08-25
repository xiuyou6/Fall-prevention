import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUserStore = defineStore('user', () => {
    const token = ref<string | null>(localStorage.getItem('X-Token'))

    const setToken = (newToken: string) => {
        token.value = newToken
        localStorage.setItem('X-Token', newToken)
    }

    const logout = () => {
        token.value = null
        localStorage.removeItem('X-Token')
    }

    return { token, setToken, logout }
})
