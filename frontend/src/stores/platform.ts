import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export const usePlatformStore = defineStore('platform', () => {
  const platforms = ref<any[]>([])
  const loading = ref(false)

  async function fetchPlatforms() {
    loading.value = true
    try {
      const { data } = await client.get('/api/platforms')
      platforms.value = data
    } catch { /* ignore */ }
    finally { loading.value = false }
  }

  return { platforms, loading, fetchPlatforms }
})
