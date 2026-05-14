import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
    { path: '/tasks', name: 'tasks', component: () => import('../views/TasksView.vue') },
    { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
    { path: '/logs', name: 'logs', component: () => import('../views/LogsView.vue') },
  ],
})

export default router
