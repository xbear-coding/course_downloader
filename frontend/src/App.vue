<script setup lang="ts">
import { RouterView, RouterLink, useRoute } from 'vue-router'
const route = useRoute()
</script>

<template>
  <div class="app">
    <nav class="nav">
      <div class="nav-brand">📥 Course_Downloader</div>
      <div class="nav-links">
        <RouterLink to="/" :class="{ active: route.path === '/' }">仪表盘</RouterLink>
        <RouterLink to="/tasks" :class="{ active: route.path === '/tasks' }">任务中心</RouterLink>
        <RouterLink to="/settings" :class="{ active: route.path === '/settings' }">设置</RouterLink>
        <RouterLink to="/logs" :class="{ active: route.path === '/logs' }">日志</RouterLink>
      </div>
    </nav>
    <main class="main"><RouterView /></main>
  </div>
</template>

<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',sans-serif; background:#0d1117; color:#e6edf3; }
.nav { display:flex; align-items:center; padding:0 24px; height:56px; background:#161b22; border-bottom:1px solid #30363d; gap:32px; }
.nav-brand { font-weight:700; font-size:16px; }
.nav-links { display:flex; gap:16px; }
.nav-links a { color:#8b949e; text-decoration:none; font-size:14px; padding:4px 0; border-bottom:2px solid transparent; }
.nav-links a.active, .nav-links a:hover { color:#e6edf3; border-bottom-color:#58a6ff; }
.main { max-width:1200px; margin:0 auto; padding:24px; }
</style>
