<script setup lang="ts">
import { RouterView, RouterLink, useRoute } from 'vue-router'
const route = useRoute()

const navItems = [
  { path: '/', name: '仪表盘', icon: '⏺' },
  { path: '/tasks', name: '任务中心', icon: '⏻' },
  { path: '/settings', name: '设置', icon: '⚙' },
  { path: '/logs', name: '日志', icon: '☰' },
]
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="brand-logo">⧉</span>
        <span class="brand-name">Course DL</span>
        <span class="brand-badge">v0.1</span>
      </div>
      <nav class="topnav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          :class="{ active: item.path === '/' ? route.path === '/' : route.path.startsWith(item.path) }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          {{ item.name }}
        </RouterLink>
      </nav>
      <div class="topbar-right">
        <span class="status-dot"></span>
        <span class="status-text">运行中</span>
      </div>
    </header>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; min-height: 100vh; }

/* ── 顶栏 ── */
.topbar {
  display: flex;
  align-items: center;
  height: 52px;
  padding: 0 28px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  gap: 32px;
  position: sticky;
  top: 0;
  z-index: 100;
}

/* 品牌 */
.brand { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.brand-logo { font-size: 20px; color: var(--blue); }
.brand-name { font-size: 15px; font-weight: 600; letter-spacing: -0.02em; }
.brand-badge { font-size: 10px; color: var(--text-dim); background: var(--bg-elevated); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }

/* 导航 */
.topnav { display: flex; gap: 4px; flex: 1; }
.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 450;
  text-decoration: none;
  transition: all var(--transition-fast);
}
.nav-link:hover { color: var(--text-primary); background: var(--bg-hover); }
.nav-link.active { color: var(--blue); background: var(--blue-bg); }
.nav-icon { font-size: 12px; opacity: 0.6; }
.nav-link.active .nav-icon { opacity: 1; }

/* 状态 */
.topbar-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px rgba(63, 185, 80, 0.5); }
.status-text { font-size: 11px; color: var(--text-muted); }

/* ── 主内容区 ── */
.main { flex: 1; max-width: 1200px; width: 100%; margin: 0 auto; }
</style>
