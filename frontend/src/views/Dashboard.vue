<script setup lang="ts">
import { onMounted } from 'vue'
import { usePlatformStore } from '../stores/platform'

const platformStore = usePlatformStore()
onMounted(() => platformStore.fetchPlatforms())
</script>

<template>
  <div class="dashboard">
    <h2>仪表盘</h2>
    <div class="platform-grid">
      <div v-for="p in platformStore.platforms" :key="p.id" class="platform-card">
        <h3>{{ p.display_name }}</h3>
        <p v-if="p.output_dir">📁 {{ p.output_dir }}</p>
      </div>
    </div>
    <p v-if="!platformStore.loading && platformStore.platforms.length === 0" class="empty">
      暂无平台数据。请先在设置中添加平台。
    </p>
  </div>
</template>

<style scoped>
.dashboard { padding: 24px; }
.platform-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 16px; }
.platform-card { background: #1c2128; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
.platform-card h3 { margin: 0 0 8px; font-size: 16px; }
.platform-card p { margin: 4px 0; font-size: 13px; color: #8b949e; }
.empty { margin-top: 24px; color: #8b949e; text-align: center; }
</style>
