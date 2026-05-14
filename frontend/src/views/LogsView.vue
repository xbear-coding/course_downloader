<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { connectWebSocket } from '../api/ws'

interface LogEntry {
  time: string
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
}

const logs = ref<LogEntry[]>([])
const logContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const filterLevel = ref<'all' | 'info' | 'success' | 'warning' | 'error'>('all')
const MAX_LOGS = 500

function addLog(message: string, type: LogEntry['type'] = 'info') {
  const now = new Date()
  const time = now.toLocaleTimeString()
  logs.value.push({ time, message, type })
  if (logs.value.length > MAX_LOGS) {
    logs.value = logs.value.slice(-MAX_LOGS)
  }
  if (autoScroll.value) {
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }
}

let wsCleanup: (() => void) | null = null

onMounted(() => {
  addLog('应用已启动', 'info')
  addLog('WebSocket 连接中...', 'info')

  wsCleanup = connectWebSocket((data) => {
    if (data.type === 'connected') {
      addLog('WebSocket 已连接', 'success')
    } else if (data.type === 'task_update') {
      addLog(`[任务 #${data.task_id}] ${data.message} (${data.total_progress}%)`, 'info')
    } else if (data.type === 'task_done') {
      addLog(`[任务 #${data.task_id}] 已完成`, 'success')
    } else if (data.type === 'task_error') {
      addLog(`[任务 #${data.task_id}] 错误: ${data.error}`, 'error')
    }
  }, (connected) => {
    if (connected) {
      addLog('WebSocket 已连接', 'success')
    } else {
      addLog('WebSocket 已断开，正在重连...', 'warning')
    }
  })
})

onUnmounted(() => {
  wsCleanup?.()
  addLog('会话已结束', 'info')
})

function clearLogs() {
  logs.value = []
}

function toggleScroll() {
  autoScroll.value = !autoScroll.value
}

const filteredLogs = () => {
  if (filterLevel.value === 'all') return logs.value
  return logs.value.filter(l => l.type === filterLevel.value)
}

const typeIcon = (type: LogEntry['type']) => {
  switch (type) {
    case 'info': return 'ℹ️'
    case 'success': return '✅'
    case 'warning': return '⚠️'
    case 'error': return '❌'
  }
}
</script>

<template>
  <div class="logs-view">
    <div class="header">
      <h2>日志</h2>
      <div class="header-actions">
        <select v-model="filterLevel" class="filter-select">
          <option value="all">全部</option>
          <option value="info">信息</option>
          <option value="success">成功</option>
          <option value="warning">警告</option>
          <option value="error">错误</option>
        </select>
        <button class="btn-sm" :class="{ active: autoScroll }" @click="toggleScroll">
          {{ autoScroll ? '自动滚动: 开' : '自动滚动: 关' }}
        </button>
        <button class="btn-sm" @click="clearLogs">清除</button>
      </div>
    </div>

    <div class="log-container" ref="logContainer">
      <div v-for="(log, i) in filteredLogs()" :key="i" class="log-line" :class="log.type">
        <span class="log-time">{{ log.time }}</span>
        <span class="log-icon">{{ typeIcon(log.type) }}</span>
        <span class="log-message">{{ log.message }}</span>
      </div>
      <div v-if="logs.length === 0" class="empty-state">
        <p>暂无日志</p>
      </div>
    </div>

    <div class="log-footer">
      <span class="text-sm">共 {{ filteredLogs().length }} 条日志</span>
      <span class="text-sm" v-if="logs.length !== filteredLogs().length">
        （已筛选，共 {{ logs.length }} 条）
      </span>
    </div>
  </div>
</template>

<style scoped>
.logs-view { padding: 24px; display: flex; flex-direction: column; height: calc(100vh - 120px); }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.header h2 { font-size: 24px; font-weight: 600; margin: 0; }
.header-actions { display: flex; gap: 8px; }

.filter-select { width: auto; min-width: 100px; padding: 4px 8px; font-size: 12px; }

.log-container {
  flex: 1; overflow-y: auto; background: #0d1117; border: 1px solid #21262d;
  border-radius: 8px; padding: 12px; font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace; font-size: 13px; line-height: 1.6;
}
.log-line { display: flex; align-items: flex-start; gap: 8px; padding: 2px 0; }
.log-line.info { color: #8b949e; }
.log-line.success { color: #3fb950; }
.log-line.warning { color: #d29922; }
.log-line.error { color: #f85149; }
.log-time { color: #484f58; white-space: nowrap; flex-shrink: 0; font-size: 12px; }
.log-icon { flex-shrink: 0; }
.log-message { word-break: break-all; }

.log-footer { display: flex; gap: 8px; margin-top: 8px; }

.btn-sm {
  background: #21262d; color: #e6edf3; border: 1px solid #30363d;
  padding: 4px 10px; font-size: 12px; border-radius: 4px;
}
.btn-sm:hover { background: #30363d; }
.btn-sm.active { background: #1f6feb; border-color: #1f6feb; }

.empty-state { text-align: center; padding: 40px; color: #484f58; }
</style>
