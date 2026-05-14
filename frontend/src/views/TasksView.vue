<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useTaskStore } from '../stores/task'
import { connectWebSocket } from '../api/ws'

const taskStore = useTaskStore()
const taskProgress = ref<Record<number, { total_progress: number; message: string }>>({})
const addingTask = ref(false)
const newPlatform = ref('tencent_meeting')
const newTitle = ref('')
const newResourceId = ref('')
const newContentType = ref('video')
const newUrl = ref('')

let wsCleanup: (() => void) | null = null

onMounted(() => {
  taskStore.fetchTasks()
  wsCleanup = connectWebSocket((data) => {
    if (data.type === 'task_update') {
      taskProgress.value[data.task_id] = {
        total_progress: data.total_progress,
        message: data.message,
      }
    } else if (data.type === 'task_done' || data.type === 'task_error') {
      delete taskProgress.value[data.task_id]
      taskStore.fetchTasks(taskStore.pagination.page)
    }
  })
})

onUnmounted(() => {
  wsCleanup?.()
})

watch(() => taskStore.platformFilter, () => taskStore.fetchTasks(1))
watch(() => taskStore.statusFilter, () => taskStore.fetchTasks(1))

async function handleAddTask() {
  if (!newTitle.value || !newResourceId.value) return
  await taskStore.createTask({
    platform: newPlatform.value,
    resource_id: newResourceId.value,
    title: newTitle.value,
    content_type: newContentType.value,
    url: newUrl.value || undefined,
  })
  addingTask.value = false
  newTitle.value = ''
  newResourceId.value = ''
  newUrl.value = ''
}

const pageInput = ref(1)
async function goPage(page: number) {
  if (page < 1 || page > taskStore.pagination.total_pages) return
  await taskStore.fetchTasks(page)
  pageInput.value = page
}

function getStatusLabel(status: string) {
  const map: Record<string, string> = {
    pending: '等待中', running: '运行中', done: '已完成',
    failed: '失败', partial: '部分完成', cancelled: '已取消',
    fatal: '严重错误', updated: '已更新', new: '新任务',
  }
  return map[status] || status
}
</script>

<template>
  <div class="tasks-view">
    <div class="header">
      <div class="header-left">
        <h2>任务中心</h2>
        <span class="count">共 {{ taskStore.pagination.total_items }} 项</span>
      </div>
      <div class="header-actions">
        <button class="btn-secondary" @click="addingTask = !addingTask">
          {{ addingTask ? '取消' : '+ 新建任务' }}
        </button>
        <button class="btn-primary" @click="taskStore.fetchTasks()">刷新</button>
      </div>
    </div>

    <!-- 新建任务表单 -->
    <div v-if="addingTask" class="add-task-form card">
      <div class="form-row">
        <div class="form-group">
          <label>平台</label>
          <select v-model="newPlatform">
            <option value="tencent_meeting">腾讯会议</option>
            <option value="xiaoe">小鹅通</option>
            <option value="bilibili">B站</option>
            <option value="xiaohongshu">小红书</option>
            <option value="toutiao">今日头条</option>
            <option value="douyin">抖音</option>
          </select>
        </div>
        <div class="form-group">
          <label>类型</label>
          <select v-model="newContentType">
            <option value="video">视频</option>
            <option value="article">文章</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>标题</label>
          <input v-model="newTitle" placeholder="内容标题" />
        </div>
        <div class="form-group">
          <label>资源 ID</label>
          <input v-model="newResourceId" placeholder="资源唯一标识" />
        </div>
      </div>
      <div class="form-group">
        <label>URL（可选）</label>
        <input v-model="newUrl" placeholder="https://..." />
      </div>
      <button class="btn-primary" @click="handleAddTask" :disabled="!newTitle || !newResourceId">
        创建任务
      </button>
    </div>

    <!-- 筛选 -->
    <div class="filters">
      <select v-model="taskStore.platformFilter">
        <option value="">全部平台</option>
        <option value="tencent_meeting">腾讯会议</option>
        <option value="xiaoe">小鹅通</option>
        <option value="bilibili">B站</option>
        <option value="xiaohongshu">小红书</option>
        <option value="toutiao">今日头条</option>
        <option value="douyin">抖音</option>
      </select>
      <select v-model="taskStore.statusFilter">
        <option value="">全部状态</option>
        <option value="pending">等待中</option>
        <option value="running">运行中</option>
        <option value="done">已完成</option>
        <option value="failed">失败</option>
        <option value="partial">部分完成</option>
        <option value="cancelled">已取消</option>
      </select>
    </div>

    <!-- 任务列表 -->
    <div class="task-list" v-if="!taskStore.loading">
      <div v-for="task in taskStore.tasks" :key="task.id" class="task-row">
        <div class="task-main">
          <div class="task-title">{{ task.title }}</div>
          <div class="task-meta">
            <span class="platform-tag">{{ task.platform }}</span>
            <span class="text-sm">{{ task.content_type }}</span>
            <span class="text-sm" v-if="task.created_at">{{ new Date(task.created_at).toLocaleString() }}</span>
          </div>
        </div>
        <div class="task-status-col">
          <span class="status-badge" :class="task.status">{{ getStatusLabel(task.status) }}</span>
          <div v-if="taskProgress[task.id]" class="task-progress">
            <div class="progress-bar">
              <div class="fill" :style="{ width: taskProgress[task.id].total_progress + '%' }"></div>
            </div>
          </div>
        </div>
        <div class="task-actions">
          <button
            v-if="task.status === 'failed' || task.status === 'partial'"
            class="btn-sm"
            @click="taskStore.retryTask(task.id)"
          >重试</button>
          <button class="btn-sm btn-danger" @click="taskStore.deleteTask(task.id)">删除</button>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="taskStore.tasks.length === 0" class="empty-state">
        <div class="icon">📋</div>
        <p>暂无任务</p>
        <p class="text-sm mt-16">点击"新建任务"创建下载任务</p>
      </div>
    </div>
    <div v-else class="loading">加载中...</div>

    <!-- 分页 -->
    <div class="pagination" v-if="taskStore.pagination.total_pages > 1">
      <button :disabled="taskStore.pagination.page <= 1" @click="goPage(taskStore.pagination.page - 1)">上一页</button>
      <div class="page-info">
        <input v-model.number="pageInput" type="number" :min="1" :max="taskStore.pagination.total_pages"
          @keyup.enter="goPage(pageInput)" />
        <span>/ {{ taskStore.pagination.total_pages }}</span>
      </div>
      <button :disabled="taskStore.pagination.page >= taskStore.pagination.total_pages"
        @click="goPage(taskStore.pagination.page + 1)">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.tasks-view { padding: 24px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header-left { display: flex; align-items: baseline; gap: 12px; }
.header-left h2 { font-size: 24px; font-weight: 600; margin: 0; }
.count { color: #8b949e; font-size: 14px; }
.header-actions { display: flex; gap: 8px; }

/* 按钮 */
.btn-primary { background: #238636; color: #fff; }
.btn-primary:hover { background: #2ea043; }
.btn-secondary { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
.btn-secondary:hover { background: #30363d; }
.btn-sm { background: #21262d; color: #e6edf3; border: 1px solid #30363d; padding: 4px 10px; font-size: 12px; border-radius: 4px; }
.btn-sm:hover { background: #30363d; }
.btn-danger { color: #f85149; border-color: #f8514933; }
.btn-danger:hover { background: rgba(248,81,73,0.15); }

/* 表单 */
.add-task-form { margin-bottom: 16px; display: flex; flex-direction: column; gap: 12px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 12px; color: #8b949e; font-weight: 500; }

/* 筛选 */
.filters { display: flex; gap: 8px; margin-bottom: 16px; }
.filters select { width: auto; min-width: 140px; }

/* 任务行 */
.task-list { display: flex; flex-direction: column; gap: 1px; background: #21262d; border-radius: 8px; overflow: hidden; }
.task-row {
  display: flex; align-items: center; gap: 16px; padding: 14px 16px;
  background: #161b22; transition: background 0.15s;
}
.task-row:hover { background: #1c2128; }
.task-main { flex: 1; min-width: 0; }
.task-title { font-weight: 500; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { display: flex; align-items: center; gap: 8px; }
.platform-tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: rgba(88,166,255,0.15); color: #58a6ff; }
.task-status-col { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 80px; }
.task-progress { width: 80px; }
.task-actions { display: flex; gap: 4px; }

/* 分页 */
.pagination { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 16px; }
.pagination button { background: #21262d; color: #e6edf3; border: 1px solid #30363d; padding: 6px 14px; border-radius: 6px; }
.pagination button:hover:not(:disabled) { background: #30363d; }
.page-info { display: flex; align-items: center; gap: 4px; color: #8b949e; font-size: 14px; }
.page-info input { width: 48px; text-align: center; padding: 4px 8px; }

.loading { text-align: center; padding: 40px; color: #8b949e; }
</style>
