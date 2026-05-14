<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../stores/settings'

const store = useSettingsStore()

const activeTab = ref<'platforms' | 'accounts' | 'keys'>('platforms')
const newAccountName = ref('')
const newAccountPlatformId = ref<number | null>(null)

const newKeyName = ref('')
const newKeyValue = ref('')
const newKeyProvider = ref('siliconflow')

const testResults = ref<Record<number, { success: boolean; message: string }>>({})
const successMessage = ref('')
const errorMessage = ref('')

onMounted(async () => {
  await store.fetchPlatforms()
  await store.fetchApiKeys()
})

function showSuccess(msg: string) {
  successMessage.value = msg
  setTimeout(() => { successMessage.value = '' }, 3000)
}

function showError(msg: string) {
  errorMessage.value = msg
  setTimeout(() => { errorMessage.value = '' }, 3000)
}

async function handleAddAccount() {
  if (!newAccountName.value || !newAccountPlatformId.value) return
  try {
    await store.createAccount(newAccountPlatformId.value, newAccountName.value)
    newAccountName.value = ''
    showSuccess('账号已添加')
  } catch (e: any) {
    showError(e.response?.data?.detail || '添加失败')
  }
}

async function handleAddKey() {
  if (!newKeyName.value || !newKeyValue.value) return
  try {
    await store.createApiKey(newKeyName.value, newKeyValue.value, newKeyProvider.value)
    newKeyName.value = ''
    newKeyValue.value = ''
    showSuccess('API Key 已添加')
  } catch (e: any) {
    showError(e.response?.data?.detail || '添加失败')
  }
}

async function handleTestKey(id: number) {
  testResults.value[id] = { success: false, message: '测试中...' }
  const result = await store.testApiKey(id)
  testResults.value[id] = result
}

async function handleDeleteKey(id: number) {
  await store.deleteApiKey(id)
  delete testResults.value[id]
  showSuccess('API Key 已删除')
}

const platformDisplayNames: Record<string, string> = {
  tencent_meeting: '腾讯会议',
  xiaoe: '小鹅通',
  bilibili: 'B站',
  xiaohongshu: '小红书',
  toutiao: '今日头条',
  douyin: '抖音',
}
</script>

<template>
  <div class="settings-view">
    <h2>设置</h2>
    <p class="subtitle">平台管理、账号配置与 API 密钥</p>

    <!-- 消息提示 -->
    <div v-if="successMessage" class="msg success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="msg error">{{ errorMessage }}</div>

    <!-- 标签页 -->
    <div class="tabs">
      <button :class="{ active: activeTab === 'platforms' }" @click="activeTab = 'platforms'">平台管理</button>
      <button :class="{ active: activeTab === 'accounts' }" @click="activeTab = 'accounts'">账号管理</button>
      <button :class="{ active: activeTab === 'keys' }" @click="activeTab = 'keys'">API 密钥</button>
    </div>

    <!-- 平台管理 -->
    <div v-if="activeTab === 'platforms'" class="tab-content">
      <div v-for="p in store.platforms" :key="p.id" class="card platform-item">
        <div class="platform-header">
          <div class="platform-info">
            <span class="platform-name">{{ p.display_name }}</span>
            <span class="platform-key">{{ p.name }}</span>
          </div>
          <span class="status-badge" :class="p.enabled ? 'done' : 'pending'">
            {{ p.enabled ? '已启用' : '已禁用' }}
          </span>
        </div>
        <div class="platform-detail">
          <div class="detail-item">
            <label>输出目录</label>
            <input :value="p.output_dir || ''" placeholder="默认输出目录" @change="(e: any) => {
              store.updatePlatform(p.id, { output_dir: e.target.value || null })
            }" />
          </div>
        </div>
      </div>
    </div>

    <!-- 账号管理 -->
    <div v-if="activeTab === 'accounts'" class="tab-content">
      <div v-for="p in store.platforms" :key="p.id" class="card mb-16">
        <div class="platform-header">
          <span class="platform-name">{{ p.display_name }}</span>
          <button class="btn-sm" @click="newAccountPlatformId = p.id; newAccountName = ''">+ 添加账号</button>
        </div>

        <!-- 添加账号表单 -->
        <div v-if="newAccountPlatformId === p.id" class="inline-form">
          <input v-model="newAccountName" placeholder="账号名称（如：熊子熠家教课）" @keyup.enter="handleAddAccount" />
          <button class="btn-primary btn-sm" @click="handleAddAccount">确认</button>
        </div>

        <!-- 账号列表 -->
        <div v-if="store.accounts[p.id]?.length" class="account-list">
          <div v-for="acct in store.accounts[p.id]" :key="acct.id" class="account-item">
            <span>{{ acct.name }}</span>
            <span class="status-badge" :class="acct.is_active ? 'done' : 'pending'">
              {{ acct.is_active ? '已登录' : '未登录' }}
            </span>
          </div>
        </div>
        <div v-else class="text-sm text-muted mt-16">
          <button class="btn-link" @click="store.fetchAccounts(p.id)">加载账号列表</button>
        </div>
      </div>
    </div>

    <!-- API 密钥 -->
    <div v-if="activeTab === 'keys'" class="tab-content">
      <div class="card mb-16">
        <div class="card-title">添加密钥</div>
        <div class="inline-form">
          <input v-model="newKeyName" placeholder="名称（如：SiliconFlow Key1）" />
          <select v-model="newKeyProvider">
            <option value="siliconflow">SiliconFlow</option>
            <option value="groq">Groq</option>
            <option value="other">其他</option>
          </select>
          <input v-model="newKeyValue" type="password" placeholder="sk-..." />
          <button class="btn-primary btn-sm" @click="handleAddKey">添加</button>
        </div>
      </div>

      <div v-for="key in store.apiKeys" :key="key.id" class="card key-item">
        <div class="key-header">
          <div class="key-info">
            <span class="key-name">{{ key.name }}</span>
            <span class="key-provider">{{ key.provider }}</span>
            <code class="key-value">{{ key.key_value }}</code>
          </div>
          <div class="key-actions">
            <button class="btn-sm" @click="handleTestKey(key.id)">测试</button>
            <button class="btn-sm btn-danger" @click="handleDeleteKey(key.id)">删除</button>
          </div>
        </div>
        <div v-if="testResults[key.id]" class="test-result" :class="{ success: testResults[key.id].success }">
          {{ testResults[key.id].message }}
        </div>
      </div>

      <div v-if="store.apiKeys.length === 0" class="empty-state">
        <div class="icon">🔑</div>
        <p>暂无 API 密钥</p>
        <p class="text-sm mt-16">添加 SiliconFlow 密钥以启用语音转写功能</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-view { padding: 24px; }
.settings-view h2 { font-size: 24px; font-weight: 600; margin: 0; }
.subtitle { color: #8b949e; margin-top: 4px; margin-bottom: 20px; font-size: 14px; }

/* 消息 */
.msg { padding: 10px 16px; border-radius: 6px; margin-bottom: 12px; font-size: 14px; }
.msg.success { background: rgba(63,185,80,0.15); color: #3fb950; border: 1px solid rgba(63,185,80,0.3); }
.msg.error { background: rgba(248,81,73,0.15); color: #f85149; border: 1px solid rgba(248,81,73,0.3); }

/* 标签页 */
.tabs { display: flex; gap: 4px; margin-bottom: 20px; background: #161b22; border-radius: 8px; padding: 4px; }
.tabs button {
  flex: 1; padding: 10px 16px; background: transparent; color: #8b949e;
  border-radius: 6px; font-size: 14px; transition: all 0.2s;
}
.tabs button.active { background: #1f6feb; color: #fff; }
.tabs button:hover:not(.active) { color: #e6edf3; }

.tab-content { display: flex; flex-direction: column; gap: 12px; }

/* 平台 */
.platform-item { display: flex; flex-direction: column; gap: 12px; }
.platform-header { display: flex; justify-content: space-between; align-items: center; }
.platform-info { display: flex; align-items: baseline; gap: 8px; }
.platform-name { font-weight: 600; font-size: 15px; }
.platform-key { font-size: 12px; color: #8b949e; }
.platform-detail { display: flex; flex-direction: column; gap: 8px; }
.detail-item { display: flex; align-items: center; gap: 8px; }
.detail-item label { font-size: 13px; color: #8b949e; min-width: 80px; }

/* 内联表单 */
.inline-form { display: flex; gap: 8px; margin-top: 12px; }
.inline-form input, .inline-form select { flex: 1; }

/* 账号列表 */
.account-list { margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
.account-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #21262d; }

/* 密钥 */
.key-item { display: flex; flex-direction: column; gap: 8px; }
.key-header { display: flex; justify-content: space-between; align-items: center; }
.key-info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.key-name { font-weight: 500; }
.key-provider { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: rgba(210,153,34,0.15); color: #d29922; }
.key-value { font-family: monospace; font-size: 12px; }
.key-actions { display: flex; gap: 4px; }
.test-result { padding: 6px 12px; border-radius: 4px; font-size: 13px; background: rgba(248,81,73,0.1); color: #f85149; }
.test-result.success { background: rgba(63,185,80,0.1); color: #3fb950; }

.btn-sm { background: #21262d; color: #e6edf3; border: 1px solid #30363d; padding: 4px 10px; font-size: 12px; border-radius: 4px; }
.btn-sm:hover { background: #30363d; }
.btn-primary { background: #238636; color: #fff; }
.btn-primary:hover { background: #2ea043; }
.btn-danger { color: #f85149; border-color: #f8514933; }
.btn-danger:hover { background: rgba(248,81,73,0.15); }
.btn-link { background: none; color: #58a6ff; padding: 0; text-decoration: underline; font-size: 13px; }
.mb-16 { margin-bottom: 16px; }
.mt-16 { margin-top: 16px; }
</style>
