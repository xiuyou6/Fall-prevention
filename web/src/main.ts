import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import router from './router'
import App from './App.vue'
import './style.css'
import { useAuthStore } from './stores/auth'
import { canAccessRole, homeForRole } from './utils/permissions'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
}

router.beforeEach(async (to) => {
    const auth = useAuthStore()
    if (!auth.ready.value) await auth.load()
    if (!to.meta.public && !auth.isAuthenticated.value) return '/login'
    if (to.meta.public && auth.user.value) return homeForRole(auth.user.value.role)
    if (auth.user.value && !canAccessRole(auth.user.value.role, to.meta.roles)) {
        return auth.user.value.role === 'elder' ? homeForRole('elder') : '/forbidden'
    }
    document.title = `${to.meta.title} - 安步守护`
    return true
})

app.mount('#app')
