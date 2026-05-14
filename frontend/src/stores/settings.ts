import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export interface PlatformItem {
  id: number
  name: string
  display_name: string
  enabled: boolean
  output_dir: string | null
  sort_order: number
}

export interface AccountItem {
  id: number
  platform_id: number
  name: string
  is_active: boolean
  last_login: string | null
}

export interface APIKeyItem {
  id: number
  name: string
  key_value: string
  provider: string
  is_active: boolean
}

export const useSettingsStore = defineStore('settings', () => {
  const platforms = ref<PlatformItem[]>([])
  const accounts = ref<Record<number, AccountItem[]>>({})
  const apiKeys = ref<APIKeyItem[]>([])
  const loading = ref(false)

  async function fetchPlatforms() {
    try {
      const { data } = await client.get('/api/platforms')
      platforms.value = data
    } catch (e) {
      console.error('获取平台列表失败:', e)
    }
  }

  async function updatePlatform(id: number, updates: Partial<PlatformItem>) {
    await client.patch(`/api/platforms/${id}`, updates)
    await fetchPlatforms()
  }

  async function fetchAccounts(platformId: number) {
    try {
      const { data } = await client.get(`/api/platforms/${platformId}/accounts`)
      accounts.value[platformId] = data
    } catch (e) {
      console.error('获取账号列表失败:', e)
    }
  }

  async function createAccount(platformId: number, name: string) {
    await client.post(`/api/platforms/${platformId}/accounts`, { platform_id: platformId, name })
    await fetchAccounts(platformId)
  }

  async function fetchApiKeys() {
    try {
      const { data } = await client.get('/api/keys')
      apiKeys.value = data
    } catch (e) {
      console.error('获取API Key列表失败:', e)
    }
  }

  async function createApiKey(name: string, keyValue: string, provider: string) {
    await client.post('/api/keys', { name, key_value: keyValue, provider })
    await fetchApiKeys()
  }

  async function deleteApiKey(id: number) {
    await client.delete(`/api/keys/${id}`)
    await fetchApiKeys()
  }

  async function testApiKey(id: number): Promise<{ success: boolean; message: string }> {
    const { data } = await client.post(`/api/keys/${id}/test`)
    return data
  }

  return {
    platforms, accounts, apiKeys, loading,
    fetchPlatforms, updatePlatform,
    fetchAccounts, createAccount,
    fetchApiKeys, createApiKey, deleteApiKey, testApiKey,
  }
})
