<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useSettingsStore } from '../stores/settings'

const store = useSettingsStore()
const activeTab = ref<'platforms' | 'accounts' | 'keys'>('platforms')

// 账号管理
const newAccountName = ref('')
const newAccountPlatformId = ref<number | null>(null)

// API Key
const newKeyName = ref('')
const newKeyValue = ref('')
const newKeyProvider = ref('siliconflow')
const testResults = ref<Record<number, { success: boolean; message: string }>>({})

// 消息
const flashMessage = ref({ show: false, type: 'success', text: '' })

function flash(type: string, text: string) {
  flashMessage.value = { show: true, type, text }
  setTimeout(() => { flashMessage.value.show = false }, 3000)
}

onMounted(async () => {
  await store.fetchPlatforms()
  await store.fetchApiKeys()
})

// ── 平台 ──
async function handleUpdatePlatform(id: number, field: string, value: any) {
  await store.updatePlatform(id, { [field]: value })
  flash('success', '已更新')
}

// ── 账号 ──
async function handleAddAccount() {
  if (!newAccountName.value || !newAccountPlatformId.value) return
  try {
    await store.createAccount(newAccountPlatformId.value, newAccountName.value)
    newAccountName.value = ''
    flash('success', '账号已添加')
  } catch { flash('error', '添加失败') }
}

// ── 目录选择器 ──
async function pickDirectory(platformId: number) {
  try {
    const handle = await (window as any).showDirectoryPicker()
    // showDirectoryPicker returns a handle with name and queryPermission
    // We'll use the name and store it as a path hint
    if (handle && handle.name) {
      // The user can type the path manually; the name shows what was selected
      flash('success', `已选择文件夹: ${handle.name}，请在输入框中填写完整路径`)
    }
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      flash('error', '选择文件夹失败')
    }
  }
}

// ── API Key ──
async function handleAddKey() {
  if (!newKeyName.value || !newKeyValue.value) return
  try {
    await store.createApiKey(newKeyName.value, newKeyValue.value, newKeyProvider.value)
    newKeyName.value = ''
    newKeyValue.value = ''
    flash('success', 'API Key 已添加')
  } catch { flash('error', '添加失败') }
}

async function handleTestKey(id: number) {
  testResults.value[id] = { success: false, message: '测试中...' }
  const result = await store.testApiKey(id)
  testResults.value[id] = result
}

async function handleDeleteKey(id: number) {
  await store.deleteApiKey(id)
  delete testResults.value[id]
  flash('success', '已删除')
}

const tabs = [
  { key: 'platforms', label: '平台管理', icon: '⊞' },
  { key: 'accounts', label: '账号管理', icon: '◉' },
  { key: 'keys', label: 'API 密钥', icon: '⚷' },
]

const platformNames: Record<string, string> = {
  tencent_meeting: '腾讯会议', xiaoe: '小鹅通', bilibili: 'B站',
  xiaohongshu: '小红书', toutiao: '今日头条', douyin: '抖音',
}

const platformIcons: Record<string, string> = {
  tencent_meeting: '🎬', xiaoe: '📚', bilibili: '📺',
  xiaohongshu: '📕', toutiao: '📰', douyin: '🎵',
}

const pathPresets = [
  { label: 'E:/BaiduSyncdisk/AI_Program/高中学习', path: 'E:/BaiduSyncdisk/AI_Program/高中学习' },
  { label: '桌面', path: '' },
  { label: '下载', path: '' },
]
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>设置</h2>
      <p class="subtitle">平台配置、账号管理与 API 密钥</p>
    </div>

    <!-- 提示消息 -->
    <div v-if="flashMessage.show" class="toast" :class="flashMessage.type">
      {{ flashMessage.text }}
    </div>

    <!-- 标签切换 -->
    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        <span class="tab-icon">{{ tab.icon }}</span>
        {{ tab.label }}
      </button>
    </div>

    <!-- ════ 平台管理 ════ -->
    <div v-if="activeTab === 'platforms'" class="tab-content">
      <div class="section-title">平台输出目录</div>
      <div class="platform-list">
        <div v-for="p in store.platforms" :key="p.id" class="platform-item card">
          <div class="pi-left">
            <span class="pi-icon">{{ platformIcons[p.name] || '📦' }}</span>
            <div class="pi-info">
              <div class="pi-name">{{ p.display_name }}</div>
              <div class="pi-key">{{ p.name }}</div>
            </div>
            <span class="status-badge" :class="p.enabled ? 'done' : 'cancelled'">
              {{ p.enabled ? '已启用' : '已禁用' }}
            </span>
          </div>
          <div class="pi-dir-row">
            <div class="dir-input-wrap">
              <input
                :value="p.output_dir || ''"
                placeholder="例如: E:/BaiduSyncdisk/AI_Program/高中学习"
                @change="(e: any) => handleUpdatePlatform(p.id, 'output_dir', (e.target as HTMLInputElement).value || null)"
              />
              <button class="btn-ghost btn-sm dir-btn" @click="pickDirectory(p.id)" title="选择文件夹">
                📁 浏览
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ════ 账号管理 ════ -->
    <div v-if="activeTab === 'accounts'" class="tab-content">
      <div class="section-title">平台账号</div>
      <div v-for="p in store.platforms" :key="p.id" class="card mb-16">
        <div class="acct-header">
          <div class="acct-title">
            <span class="acct-icon">{{ platformIcons[p.name] || '📦' }}</span>
            <span>{{ p.display_name }}</span>
          </div>
          <button class="btn-secondary btn-sm" @click="newAccountPlatformId = p.id; newAccountName = ''">
            ＋ 添加账号
          </button>
        </div>

        <!-- 添加表单 -->
        <div v-if="newAccountPlatformId === p.id" class="acct-form">
          <input v-model="newAccountName" placeholder="账号名称（如：熊子熠）" @keyup.enter="handleAddAccount" />
          <button class="btn-primary btn-sm" @click="handleAddAccount">确认</button>
        </div>

        <!-- 账号列表 -->
        <div v-if="store.accounts[p.id]?.length" class="acct-list">
          <div v-for="a in store.accounts[p.id]" :key="a.id" class="acct-row">
            <span>{{ a.name }}</span>
            <span class="status-badge" :class="a.is_active ? 'done' : 'pending'">
              {{ a.is_active ? '已登录' : '未登录' }}
            </span>
          </div>
        </div>
        <div v-else class="text-sm mt-12">
          <button class="btn-ghost btn-sm" @click="store.fetchAccounts(p.id)">加载账号列表</button>
        </div>
      </div>
    </div>

    <!-- ════ API 密钥 ════ -->
    <div v-if="activeTab === 'keys'" class="tab-content">
      <div class="section-title">API 密钥管理</div>

      <!-- 添加密钥 -->
      <div class="card mb-16">
        <div class="card-title">添加密钥</div>
        <div class="key-form">
          <input v-model="newKeyName" placeholder="名称" />
          <select v-model="newKeyProvider">
            <option value="siliconflow">SiliconFlow</option>
            <option value="groq">Groq</option>
            <option value="other">其他</option>
          </select>
          <input v-model="newKeyValue" type="password" placeholder="sk-..." />
          <button class="btn-primary btn-sm" :disabled="!newKeyName || !newKeyValue" @click="handleAddKey">
            添加
          </button>
        </div>
      </div>

      <!-- 密钥列表 -->
      <div class="key-list">
        <div v-for="key in store.apiKeys" :key="key.id" class="key-item card">
          <div class="key-row">
            <div class="key-info">
              <span class="key-name">{{ key.name }}</span>
              <span class="key-provider">{{ key.provider }}</span>
              <code class="key-value">{{ key.key_value }}</code>
            </div>
            <div class="key-actions">
              <button class="btn-sm" :class="testResults[key.id]?.success ? 'btn-primary' : 'btn-secondary'"
                @click="handleTestKey(key.id)">
                {{ testResults[key.id] ? '重测' : '测试' }}
              </button>
              <button class="btn-sm btn-danger" @click="handleDeleteKey(key.id)">删除</button>
            </div>
          </div>
          <div v-if="testResults[key.id]" class="test-msg" :class="{ ok: testResults[key.id].success }">
            {{ testResults[key.id].message }}
          </div>
        </div>
      </div>

      <div v-if="store.apiKeys.length === 0" class="empty-state">
        <div class="icon">⚷</div>
        <p>暂无 API 密钥</p>
        <p class="text-sm mt-8">添加 SiliconFlow 密钥以启用语音转写</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 32px 36px; }

/* ── 消息提示 ── */
.toast {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 1000;
  padding: 10px 20px;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 500;
  animation: slideIn 0.25s ease;
}
.toast.success { background: var(--green-bg); color: var(--green); border: 1px solid rgba(63,185,80,0.3); }
.toast.error { background: var(--red-bg); color: var(--red); border: 1px solid rgba(248,81,73,0.3); }
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* ── 标签页 ── */
.tabs { display: flex; gap: 4px; margin-bottom: 24px; }
.tab-btn {
  padding: 8px 18px;
  background: transparent;
  color: var(--text-muted);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-size: 13px;
  transition: all var(--transition-fast);
}
.tab-btn:hover { color: var(--text-primary); background: var(--bg-hover); }
.tab-btn.active { color: var(--blue); background: var(--blue-bg); border-color: var(--border-accent); }
.tab-icon { font-size: 15px; }

/* ── 平台列表 ── */
.platform-list { display: flex; flex-direction: column; gap: 10px; }

.platform-item { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.pi-left { display: flex; align-items: center; gap: 12px; }
.pi-icon { font-size: 22px; }
.pi-info { flex: 1; }
.pi-name { font-weight: 600; font-size: 14px; }
.pi-key { font-size: 11px; color: var(--text-dim); font-family: var(--font-mono); margin-top: 1px; }

.pi-dir-row { display: flex; flex-direction: column; gap: 6px; }
.dir-input-wrap {
  display: flex;
  gap: 6px;
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 2px;
}
.dir-input-wrap input {
  flex: 1;
  border: none;
  background: transparent;
  padding: 6px 10px;
}
.dir-input-wrap input:focus { box-shadow: none; }
.dir-btn { flex-shrink: 0; margin-right: 2px; }

/* ── 账号 ── */
.acct-header { display: flex; justify-content: space-between; align-items: center; }
.acct-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; }
.acct-icon { font-size: 18px; }
.acct-form { display: flex; gap: 8px; margin-top: 12px; }
.acct-form input { flex: 1; }
.acct-list { margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
.acct-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }

/* ── API Key ── */
.key-form { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.key-form select { min-width: 0; }
.key-form button { grid-column: 1 / -1; justify-content: center; }
.key-list { display: flex; flex-direction: column; gap: 8px; }
.key-item { padding: 14px 16px; }
.key-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.key-info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.key-name { font-weight: 500; font-size: 13px; color: var(--text-primary); }
.key-provider { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: var(--purple-bg); color: var(--purple); }
.key-value { font-size: 12px; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; }
.key-actions { display: flex; gap: 4px; flex-shrink: 0; }
.test-msg { margin-top: 8px; padding: 6px 12px; border-radius: var(--radius-sm); font-size: 12px; background: var(--red-bg); color: var(--red); }
.test-msg.ok { background: var(--green-bg); color: var(--green); }

.mb-16 { margin-bottom: 16px; }
.mt-12 { margin-top: 12px; }
.mt-8 { margin-top: 8px; }
</style>
