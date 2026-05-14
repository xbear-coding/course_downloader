<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { usePlatformStore } from '../stores/platform'
import { useTaskStore } from '../stores/task'
import { connectWebSocket } from '../api/ws'

const platformStore = usePlatformStore()
const taskStore = useTaskStore()

const taskProgress = ref<Record<number, { total_progress: number; message: string }>>({})
const totalTasks = ref(0)
const doneTasks = ref(0)
const failedTasks = ref(0)

let wsCleanup: (() => void) | null = null

onMounted(() => {
  platformStore.fetchPlatforms()
  loadStats()
  wsCleanup = connectWebSocket((data) => {
    if (data.type === 'task_update') {
      taskProgress.value[data.task_id] = {
        total_progress: data.total_progress,
        message: data.message,
      }
    } else if (data.type === 'task_done') {
      delete taskProgress.value[data.task_id]
      loadStats()
    } else if (data.type === 'task_error') {
      delete taskProgress.value[data.task_id]
      loadStats()
    }
  })
})

onUnmounted(() => {
  wsCleanup?.()
})

async function loadStats() {
  try {
    const { data } = await (await import('../api/client')).default.get('/api/tasks', { params: { page_size: 1 } })
    totalTasks.value = data.pagination.total_items
    // Also load done/failed counts via filters
    const done = await (await import('../api/client')).default.get('/api/tasks', { params: { status: 'done', page_size: 1 } })
    doneTasks.value = done.data.pagination.total_items
    const failed = await (await import('../api/client')).default.get('/api/tasks', { params: { status: 'failed', page_size: 1 } })
    failedTasks.value = failed.data.pagination.total_items
  } catch {}
}

const platformIcons: Record<string, string> = {
  tencent_meeting: '🎬',
  xiaoe: '📚',
  bilibili: '📺',
  xiaohongshu: '📕',
  toutiao: '📰',
  douyin: '🎵',
}

const platformColors: Record<string, string> = {
  tencent_meeting: '#6366f1',
  xiaoe: '#f59e0b',
  bilibili: '#fb7299',
  xiaohongshu: '#ff2442',
  toutiao: '#1e80ff',
  douyin: '#00f2ea',
}

function getPlatformIcon(name: string) {
  return platformIcons[name] || '📦'
}

function getPlatformColor(name: string) {
  return platformColors[name] || '#58a6ff'
}
</script>

<template>
  <div class="dashboard">
    <div class="header">
      <h2>仪表盘</h2>
      <p class="subtitle">多平台内容下载中心</p>
    </div>

    <!-- 统计概览 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">{{ totalTasks }}</div>
        <div class="stat-label">总任务</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:#3fb950">{{ doneTasks }}</div>
        <div class="stat-label">已完成</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:#f85149">{{ failedTasks }}</div>
        <div class="stat-label">失败</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ platformStore.platforms.filter(p => p.enabled).length }}</div>
        <div class="stat-label">活跃平台</div>
      </div>
    </div>

    <!-- 平台卡片 -->
    <h3 class="section-title">平台</h3>
    <div class="platform-grid">
      <div
        v-for="p in platformStore.platforms"
        :key="p.id"
        class="platform-card"
        :style="{ borderLeftColor: getPlatformColor(p.name) }"
        @click="$router.push('/settings')"
      >
        <div class="platform-icon">{{ getPlatformIcon(p.name) }}</div>
        <div class="platform-info">
          <div class="platform-name">{{ p.display_name }}</div>
          <div class="platform-dir" v-if="p.output_dir">{{ p.output_dir }}</div>
          <div class="platform-dir" v-else>未设置输出目录</div>
        </div>
        <div class="platform-status" :class="{ active: p.enabled }">
          {{ p.enabled ? '已启用' : '已禁用' }}
        </div>
      </div>
    </div>

    <!-- 运行中的任务 -->
    <div v-if="Object.keys(taskProgress).length > 0" class="running-section">
      <h3 class="section-title">运行中的任务</h3>
      <div v-for="(prog, id) in taskProgress" :key="id" class="running-item card">
        <div class="flex items-center justify-between mb-16">
          <span class="text-sm">任务 #{{ id }}</span>
          <span class="text-sm">{{ prog.total_progress }}%</span>
        </div>
        <div class="progress-bar">
          <div class="fill" :style="{ width: prog.total_progress + '%' }"></div>
        </div>
        <div class="text-sm mt-16">{{ prog.message }}</div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!platformStore.loading && platformStore.platforms.length === 0" class="empty-state">
      <div class="icon">📦</div>
      <p>暂无平台数据</p>
      <p class="text-sm mt-16">请先在设置中添加平台</p>
    </div>
  </div>
</template>

<style scoped>
.dashboard { padding: 24px; }
.header { margin-bottom: 24px; }
.header h2 { font-size: 24px; font-weight: 600; margin: 0; }
.subtitle { color: #8b949e; margin-top: 4px; font-size: 14px; }
.section-title { font-size: 16px; font-weight: 600; margin: 24px 0 12px; }

/* 统计卡片 */
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 8px; }
@media (max-width: 600px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card {
  background: #161b22; border: 1px solid #30363d; border-radius: 8px;
  padding: 20px; text-align: center;
}
.stat-value { font-size: 32px; font-weight: 700; color: #e6edf3; }
.stat-label { font-size: 12px; color: #8b949e; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }

/* 平台卡片 */
.platform-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 900px) { .platform-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .platform-grid { grid-template-columns: 1fr; } }
.platform-card {
  background: #161b22; border: 1px solid #30363d; border-left: 3px solid #30363d;
  border-radius: 8px; padding: 16px; cursor: pointer; display: flex; align-items: center; gap: 12px;
  transition: border-color 0.2s, background 0.2s;
}
.platform-card:hover { background: #1c2128; }
.platform-icon { font-size: 28px; }
.platform-info { flex: 1; min-width: 0; }
.platform-name { font-weight: 600; font-size: 15px; }
.platform-dir { font-size: 12px; color: #8b949e; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.platform-status { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(139,148,158,0.15); color: #8b949e; white-space: nowrap; }
.platform-status.active { background: rgba(63,185,80,0.15); color: #3fb950; }

/* 运行中的任务 */
.running-section { margin-top: 8px; }
.running-item { margin-bottom: 12px; }
</style>
