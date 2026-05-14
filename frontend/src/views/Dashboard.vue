<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { usePlatformStore } from '../stores/platform'
import client from '../api/client'
import { connectWebSocket } from '../api/ws'

const platformStore = usePlatformStore()

const stats = ref({ total: 0, done: 0, failed: 0, partial: 0 })
const taskProgress = ref<Record<number, { total_progress: number; message: string; step: string }>>({})

let wsCleanup: (() => void) | null = null

onMounted(() => {
  platformStore.fetchPlatforms()
  loadStats()
  wsCleanup = connectWebSocket((data) => {
    if (data.type === 'task_update') {
      taskProgress.value[data.task_id] = {
        total_progress: data.total_progress,
        message: data.message,
        step: data.step,
      }
    } else if (data.type === 'task_done' || data.type === 'task_error') {
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
    const [all, done, failed, partial] = await Promise.all([
      client.get('/api/tasks', { params: { page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'done', page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'failed', page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'partial', page_size: 1 } }),
    ])
    stats.value = {
      total: all.data.pagination.total_items,
      done: done.data.pagination.total_items,
      failed: failed.data.pagination.total_items,
      partial: partial.data.pagination.total_items,
    }
  } catch {}
}

const platformMeta: Record<string, { icon: string; desc: string }> = {
  tencent_meeting: { icon: '🎬', desc: '会议录制' },
  xiaoe: { icon: '📚', desc: '课程' },
  bilibili: { icon: '📺', desc: '视频' },
  xiaohongshu: { icon: '📕', desc: '图文' },
  toutiao: { icon: '📰', desc: '资讯' },
  douyin: { icon: '🎵', desc: '短视频' },
}

const runningTasks = () => Object.keys(taskProgress.value).length
</script>

<template>
  <div class="dashboard">
    <div class="page-header">
      <h2>仪表盘</h2>
      <p class="subtitle">多平台内容下载中心</p>
    </div>

    <!-- 统计行 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">总任务</div>
        <div v-if="runningTasks() > 0" class="stat-badge pulse">● {{ runningTasks() }} 运行中</div>
      </div>
      <div class="stat-card stat-done">
        <div class="stat-value">{{ stats.done }}</div>
        <div class="stat-label">已完成</div>
      </div>
      <div class="stat-card stat-failed">
        <div class="stat-value">{{ stats.failed }}</div>
        <div class="stat-label">失败</div>
      </div>
      <div class="stat-card stat-partial">
        <div class="stat-value">{{ stats.partial }}</div>
        <div class="stat-label">部分完成</div>
      </div>
    </div>

    <!-- 进行中的任务 -->
    <div v-if="runningTasks() > 0" class="section">
      <h3 class="section-title">进行中</h3>
      <div class="running-list">
        <div v-for="(prog, id) in taskProgress" :key="id" class="running-item card">
          <div class="running-header">
            <span class="running-id">#{{ id }}</span>
            <span class="running-step">{{ prog.step }}</span>
          </div>
          <div class="running-bar">
            <div class="progress-bar">
              <div class="fill" :style="{ width: prog.total_progress + '%' }"></div>
            </div>
            <span class="running-pct">{{ prog.total_progress }}%</span>
          </div>
          <div class="running-msg">{{ prog.message }}</div>
        </div>
      </div>
    </div>

    <!-- 平台网格 -->
    <div class="section">
      <h3 class="section-title">平台</h3>
      <div class="platform-grid">
        <div
          v-for="p in platformStore.platforms"
          :key="p.id"
          class="platform-card card"
          @click="$router.push('/settings')"
        >
          <div class="platform-header">
            <span class="platform-icon">{{ platformMeta[p.name]?.icon || '📦' }}</span>
            <span class="platform-indicator" :class="{ on: p.enabled }"></span>
          </div>
          <div class="platform-name">{{ p.display_name }}</div>
          <div class="platform-type">{{ platformMeta[p.name]?.desc || '' }}</div>
          <div class="platform-dir">{{ p.output_dir || '未设置输出目录' }}</div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!platformStore.loading && platformStore.platforms.length === 0" class="empty-state">
      <div class="icon">⧉</div>
      <p>暂无平台数据</p>
      <p class="text-sm mt-16">请在设置中添加平台</p>
    </div>
  </div>
</template>

<style scoped>
.dashboard { padding: 28px 32px; }

/* 统计行 */
.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }
@media (max-width: 640px) { .stats-row { grid-template-columns: repeat(2, 1fr); } }

.stat-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  position: relative;
}
.stat-value { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 2px; }
.stat-badge {
  position: absolute; top: 12px; right: 14px;
  font-size: 10px; color: var(--blue);
  background: var(--blue-bg);
  padding: 2px 8px;
  border-radius: 100px;
}
.pulse { animation: pulse-dot 2s ease-in-out infinite; }
.stat-done .stat-value { color: var(--green); }
.stat-failed .stat-value { color: var(--red); }
.stat-partial .stat-value { color: var(--amber); }

@keyframes pulse-dot {
  0%, 100% { opacity: 1; } 50% { opacity: 0.5; }
}

/* 进行中任务 */
.section { margin-bottom: 28px; }
.section-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  margin-bottom: 12px;
  font-weight: 500;
}
.running-list { display: flex; flex-direction: column; gap: 10px; }
.running-item { padding: 16px 18px; }
.running-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.running-id { font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary); }
.running-step { font-size: 11px; color: var(--text-muted); background: var(--bg-surface); padding: 2px 8px; border-radius: 100px; }
.running-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.running-bar .progress-bar { flex: 1; }
.running-pct { font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); min-width: 32px; text-align: right; }
.running-msg { font-size: 12px; color: var(--text-secondary); }

/* 平台网格 */
.platform-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 900px) { .platform-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) { .platform-grid { grid-template-columns: 1fr; } }

.platform-card {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px;
  transition: all var(--transition-fast);
}
.platform-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent-subtle);
}
.platform-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.platform-icon { font-size: 24px; }
.platform-indicator {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--gray);
  transition: background var(--transition-fast);
}
.platform-indicator.on { background: var(--green); box-shadow: 0 0 6px rgba(52, 211, 153, 0.4); }
.platform-name { font-weight: 600; font-size: 14px; }
.platform-type { font-size: 11px; color: var(--text-muted); }
.platform-dir { font-size: 11px; color: var(--text-dim); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
