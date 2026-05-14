<script setup lang="ts">
import { RouterView, RouterLink, useRoute } from 'vue-router'
const route = useRoute()

const navItems = [
  { path: '/', name: '仪表盘', icon: '◉' },
  { path: '/tasks', name: '任务中心', icon: '⊞' },
  { path: '/settings', name: '设置', icon: '⚙' },
  { path: '/logs', name: '日志', icon: '☰' },
]
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-mark">⧉</span>
        <div class="brand-text">
          <span class="brand-title">Course DL</span>
          <span class="brand-version">v0.1</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: item.path === '/' ? route.path === '/' : route.path.startsWith(item.path) }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.name }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <span class="footer-dot"></span>
        <span class="footer-text">离线下载工具</span>
      </div>
    </aside>

    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}

/* 侧边栏 */
.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 0;
  position: sticky;
  top: 0;
  height: 100vh;
}

/* 品牌标识 */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 24px;
  border-bottom: 1px solid var(--border);
}
.brand-mark {
  font-size: 22px;
  color: var(--accent);
  font-weight: 300;
}
.brand-text {
  display: flex;
  flex-direction: column;
}
.brand-title {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.brand-version {
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  margin-top: -1px;
}

/* 导航 */
.sidebar-nav {
  flex: 1;
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-decoration: none;
  transition: all var(--transition-fast);
  font-size: 13px;
  font-weight: 450;
}
.nav-item:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.nav-item.active {
  color: var(--accent);
  background: var(--accent-subtle);
}
.nav-icon {
  font-size: 15px;
  width: 18px;
  text-align: center;
  opacity: 0.7;
}
.nav-item.active .nav-icon {
  opacity: 1;
}

/* 底部状态 */
.sidebar-footer {
  padding: 16px 18px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}
.footer-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
}
.footer-text {
  font-size: 11px;
  color: var(--text-dim);
}

/* 主内容区 */
.main-content {
  flex: 1;
  min-width: 0;
  padding: 0;
  max-width: 1200px;
  width: 100%;
}
</style>
