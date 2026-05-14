import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export interface TaskItem {
  id: number
  platform: string
  resource_id: string | null
  title: string
  content_type: string
  status: string
  video_path: string | null
  transcript_path: string | null
  error_message: string | null
  retry_count: number
  created_at: string
  downloaded_at: string | null
}

export interface PaginationInfo {
  page: number
  page_size: number
  total_items: number
  total_pages: number
}

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<TaskItem[]>([])
  const pagination = ref<PaginationInfo>({ page: 1, page_size: 20, total_items: 0, total_pages: 0 })
  const loading = ref(false)
  const platformFilter = ref('')
  const statusFilter = ref('')

  async function fetchTasks(page = 1) {
    loading.value = true
    try {
      const params: any = { page, page_size: 20 }
      if (platformFilter.value) params.platform = platformFilter.value
      if (statusFilter.value) params.status = statusFilter.value
      const { data } = await client.get('/api/tasks', { params })
      tasks.value = data.data
      pagination.value = data.pagination
    } catch (e) {
      console.error('获取任务列表失败:', e)
    } finally {
      loading.value = false
    }
  }

  async function createTask(task: { platform: string; resource_id: string; title: string; content_type?: string; url?: string }) {
    const { data } = await client.post('/api/tasks', task)
    await fetchTasks(1)
    return data
  }

  async function retryTask(taskId: number) {
    await client.post(`/api/tasks/${taskId}/retry`)
    await fetchTasks(pagination.value.page)
  }

  async function deleteTask(taskId: number) {
    await client.delete(`/api/tasks/${taskId}`)
    await fetchTasks(pagination.value.page)
  }

  return { tasks, pagination, loading, platformFilter, statusFilter, fetchTasks, createTask, retryTask, deleteTask }
})
