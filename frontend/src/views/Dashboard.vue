<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { usePlatformStore } from '../stores/platform'
import client from '../api/client'
import { connectWebSocket } from '../api/ws'

const platformStore = usePlatformStore()

const stats = ref({ total: 0, done: 0, failed: 0, partial: 0, running: 0 })
const taskProgress = ref<Record<number, { total_progress: number; message: string; step: string }>>({})

let wsCleanup: (() => void) | null = null

onMounted(() => {
  platformStore.fetchPlatforms()
  loadStats()
  wsCleanup = connectWebSocket((data) => {
    if (data.type === 'task_update' && !['pending','cancelled'].includes(data.step)) {
      taskProgress.value[data.task_id] = {
        total_progress: data.total_progress,
        message: data.message,
        step: data.step,
      }
      stats.value.running = Object.keys(taskProgress.value).length
    } else if (['task_done', 'task_error'].includes(data.type)) {
      delete taskProgress.value[data.task_id]
      stats.value.running = Object.keys(taskProgress.value).length
      loadStats()
    }
  })
})

onUnmounted(() => { wsCleanup?.() })

async function loadStats() {
  try {
    const [all, done, failed, partial, running] = await Promise.all([
      client.get('/api/tasks', { params: { page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'done', page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'failed', page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'partial', page_size: 1 } }),
      client.get('/api/tasks', { params: { status: 'running', page_size: 1 } }),
    ])
    stats.value = {
      total: all.data.pagination.total_items,
      done: done.data.pagination.total_items,
      failed: failed.data.pagination.total_items,
      partial: partial.data.pagination.total_items,
      running: running.data.pagination.total_items || Object.keys(taskProgress.value).length,
    }
  } catch {}
}

const platformMeta: Record<string, { icon: string; desc: string }> = {
  tencent_meeting: { icon: '🎬', desc: '会议录制' },
  xiaoe: { icon: '📚', desc: '知识课程' },
  bilibili: { icon: '📺', desc: '视频平台' },
  xiaohongshu: { icon: '📕', desc: '社交图文' },
  toutiao: { icon: '📰', desc: '资讯文章' },
  douyin: { icon: '🎵', desc: '短视频' },
}

const cdn = (n: number) => n >= 1000 ? (n/1000).toFixed(1) + 'k' : String(n)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>仪表盘</h2>
      <p class="subtitle">多平台内容下载中心</p>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <div class="stat-card card-total">
        <div class="stat-value">{{ cdn(stats.total) }}</div>
        <div class="stat-label">总任务</div>
        <div class="stat-trend" v-if="stats.running > 0">{{ stats.running }} 进行中</div>
      </div>
      <div class="stat-card card-done">
        <div class="stat-value">{{ cdn(stats.done) }}</div>
        <div class="stat-label">已完成</div>
        <div class="stat-trend" v-if="stats.total > 0">{{ stats.total ? Math.round(stats.done/stats.total*100) : 0 }}%</div>
      </div>
      <div class="stat-card card-failed">
        <div class="stat-value">{{ cdn(stats.failed) }}</div>
        <div class="stat-label">失败</div>
        <div class="stat-trend" v-if="stats.failed > 0">需关注</div>
      </div>
      <div class="stat-card card-partial">
        <div class="stat-value">{{ cdn(stats.partial) }}</div>
        <div class="stat-label">部分完成</div>
      </div>
    </div>

    <!-- 进行中 -->
    <div v-if="stats.running > 0" class="section">
      <div class="section-title">进行中</div>
      <div class="run-list">
        <div v-for="(p, id) in taskProgress" :key="id" class="run-item card">
          <div class="run-head">
            <div class="run-id text-mono">#{{ id }}</div>
            <div class="run-step">{{ p.step }}</div>
          </div>
          <div class="run-bar">
            <div class="progress-bar">
              <div class="fill" :style="{ width: p.total_progress + '%' }"></div>
            </div>
            <span class="run-pct text-mono">{{ p.total_progress }}%</span>
          </div>
          <div class="run-msg text-sm">{{ p.message }}</div>
        </div>
      </div>
    </div>

    <!-- 平台网格 -->
    <div class="section">
      <div class="section-title">平台</div>
      <div class="plat-grid">
        <div
          v-for="p in platformStore.platforms"
          :key="p.id"
          class="plat-card card"
          @click="$router.push('/settings')"
        >
          <div class="plat-head">
            <span class="plat-icon">{{ platformMeta[p.name]?.icon || '📦' }}</span>
            <span class="plat-dot" :class="{ on: p.enabled }"></span>
          </div>
          <div class="plat-name">{{ p.display_name }}</div>
          <div class="plat-desc">{{ platformMeta[p.name]?.desc || '' }}</div>
          <div class="plat-dir">
            <span class="dir-label">输出</span>
            <span class="dir-path">{{ p.output_dir || '未设置' }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!platformStore.loading && platformStore.platforms.length === 0" class="empty-state">
      <div class="icon">⧉</div>
      <p>暂无平台</p>
      <p class="text-sm mt-8">请在设置中添加平台</p>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 32px 36px; }

/* ── 统计 ── */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }
@media (max-width: 640px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  position: relative;
  overflow: hidden;
}
.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
}
.card-total::before { background: var(--blue); }
.card-done::before { background: var(--green); }
.card-failed::before { background: var(--red); }
.card-partial::before { background: var(--orange); }

.stat-value { font-size: 30px; font-weight: 700; letter-spacing: -0.04em; font-variant-numeric: tabular-nums; }
.card-done .stat-value { color: var(--green); }
.card-failed .stat-value { color: var(--red); }
.card-partial .stat-value { color: var(--orange); }

.stat-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 2px; }
.stat-trend {
  display: inline-block;
  margin-top: 6px;
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 100px;
  background: var(--blue-bg);
  color: var(--blue);
}
.card-done .stat-trend { background: var(--green-bg); color: var(--green); }
.card-failed .stat-trend { background: var(--red-bg); color: var(--red); }

/* ── 进行中 ── */
.section { margin-bottom: 28px; }
.run-list { display: flex; flex-direction: column; gap: 8px; }
.run-item { padding: 14px 18px; }
.run-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.run-id { font-size: 12px; color: var(--text-muted); }
.run-step { font-size: 10px; padding: 2px 8px; border-radius: 100px; background: var(--blue-bg); color: var(--blue); text-transform: uppercase; letter-spacing: 0.05em; }
.run-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.run-bar .progress-bar { flex: 1; }
.run-pct { font-size: 12px; color: var(--text-muted); min-width: 36px; text-align: right; }
.run-msg { font-size: 12px; }

/* ── 平台 ── */
.plat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 900px) { .plat-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) { .plat-grid { grid-template-columns: 1fr; } }

.plat-card {
  cursor: pointer;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all var(--transition-normal);
}
.plat-card:hover { border-color: var(--blue); box-shadow: var(--shadow-glow-blue); transform: translateY(-1px); }

.plat-head { display: flex; justify-content: space-between; align-items: center; }
.plat-icon { font-size: 26px; }
.plat-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-dim); }
.plat-dot.on { background: var(--green); box-shadow: 0 0 8px rgba(63, 185, 80, 0.5); }

.plat-name { font-weight: 600; font-size: 15px; margin-top: 2px; }
.plat-desc { font-size: 12px; color: var(--text-muted); }

.plat-dir {
  margin-top: 6px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--bg-surface);
  border-radius: var(--radius-sm);
}
.dir-label { color: var(--text-dim); }
.dir-path { color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.mt-8 { margin-top: 8px; }
</style>
