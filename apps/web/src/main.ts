/**
 * Vue app bootstrap: Pinia + router.
 * Enable verbose API logs in console: localStorage.setItem('TDASHBOARD_DEBUG','1')
 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles.css'
import { createLogger } from './utils/logger'

const log = createLogger('boot')
log.info('mounting app')

createApp(App).use(createPinia()).use(router).mount('#app')
