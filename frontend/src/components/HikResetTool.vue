<template>
  <div class="reset-tool">
    <!-- Tabs -->
    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['tab-btn', { active: activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- QR Code Upload Tab -->
    <div v-if="activeTab === 'qr'" class="tab-content card">
      <h2>📷 上传二维码截图</h2>
      <p class="description">
        上传 SADP 工具中生成的密码重置二维码截图。系统将自动解码二维码内容，
        并尝试通过海康威视服务 API 自动获取重置密钥。<br />
        Upload a screenshot of the password reset QR code from the SADP tool.
        The system will decode the QR code and try to obtain the reset key
        automatically via Hikvision's service API.<br /><br />
        <strong>操作流程：</strong>海康威视客户服务 → 贴心服务 → 密码重置 → 使用小程序扫码 → 获取密钥。
        本工具通过解码二维码并自动提交，帮助您快速获取密钥。<br />
        <strong>Flow:</strong> Hikvision Customer Service → Service Support → Password Reset →
        scan with mini-program → get key. This tool decodes the QR and auto-submits to help you get the key faster.
      </p>

      <!-- Drag & Drop / Click Upload Area -->
      <div
        class="upload-area"
        :class="{ dragover: isDragging, 'has-image': previewUrl }"
        @click="triggerFileInput"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          style="display: none"
          @change="handleFileChange"
        />
        <div v-if="!previewUrl" class="upload-placeholder">
          <div class="upload-icon">📁</div>
          <p>点击或拖拽截图到此处</p>
          <p class="hint">支持 PNG、JPG、BMP 等格式</p>
        </div>
        <div v-else class="preview-container">
          <img :src="previewUrl" alt="QR Code Preview" class="preview-image" />
        </div>
      </div>

      <!-- Paste Hint -->
      <p class="paste-hint">💡 也可以直接 <kbd>Ctrl+V</kbd> 粘贴截图</p>

      <!-- Action Buttons -->
      <div class="actions">
        <button
          class="btn btn-primary"
          :disabled="!selectedFile || isLoading"
          @click="uploadQrImage"
        >
          <span v-if="isLoading" class="spinner">⟳</span>
          <span v-else>🔍 解码并获取密钥</span>
        </button>
        <button v-if="selectedFile" class="btn btn-secondary" @click="clearImage">
          🗑️ 清除
        </button>
      </div>
    </div>

    <!-- Offline Key Generation Tab -->
    <div v-if="activeTab === 'offline'" class="tab-content card">
      <h2>⚙️ 离线密钥生成</h2>

      <div class="firmware-warning">
        <strong>⚠️ 仅适用于旧固件 / Only for older firmware:</strong>
        <ul>
          <li>此离线算法<strong>仅适用于固件 &lt; 5.3.0</strong> 的设备（通常为 2017 年以前出厂的设备）。
              This offline algorithm <strong>ONLY works for firmware &lt; 5.3.0</strong> (typically devices manufactured before 2017).</li>
          <li>新固件设备（≥ 5.3.0，如 v5.x / v7.x）不支持此方式，请查看下方"新固件重置方法"。
              Newer firmware (≥ 5.3.0, e.g. v5.x / v7.x) is NOT supported — see "New Firmware Reset Methods" below.</li>
        </ul>
      </div>

      <p class="description">
        输入 SADP 中显示的设备序列号和设备内部日期（Start Time 列），离线生成重置安全码。<br />
        <strong>注意：日期必须与设备内部时间一致（非今日日期），请重启设备后在 SADP 的 Start Time 列查看。</strong><br />
        Enter the serial number and the device's internal date (Start Time column in SADP).<br />
        <strong>Note: The date must match the device's internal clock (NOT today's date).
        Reboot the device and check the Start Time column in SADP.</strong>
      </p>
      <div class="form-group">
        <label>设备序列号 (Serial Number)</label>
        <input
          v-model="offlineSerial"
          type="text"
          placeholder="例如: DS-2CD2T45G0P-I20190101XXXX"
          class="input"
        />
      </div>
      <div class="form-group">
        <label>SADP 中显示的设备日期</label>
        <input v-model="offlineDate" type="date" class="input" />
      </div>
      <div class="actions">
        <button
          class="btn btn-primary"
          :disabled="!offlineSerial.trim() || !offlineDate || isLoading"
          @click="generateOfflineKey"
        >
          <span v-if="isLoading" class="spinner">⟳</span>
          <span v-else>🔑 生成密钥</span>
        </button>
      </div>
    </div>

    <!-- Result Display (single result) -->
    <div v-if="result" class="result-container">
      <!-- Success -->
      <div v-if="result.key" class="result-card success">
        <div class="result-header">
          <span class="result-icon">✅</span>
          <h3>密钥获取成功！</h3>
        </div>
        <div class="key-display">
          <span class="key-label">重置密钥 (Reset Key):</span>
          <div class="key-value-row">
            <code class="key-value">{{ result.key }}</code>
            <button class="copy-btn" @click="copyKey(result.key!)" :title="'复制密钥'">
              {{ copied ? '✅ 已复制' : '📋 复制' }}
            </button>
          </div>
        </div>
        <div v-if="result.method" class="result-meta">
          <span class="meta-label">获取方式:</span>
          <span class="meta-value">{{ methodLabel(result.method) }}</span>
        </div>
        <div v-if="result.error" class="result-note warning">
          <strong>注意:</strong> {{ result.error }}
        </div>
        <div v-if="result.qr_content" class="result-qr-content">
          <span class="meta-label">二维码内容:</span>
          <code class="qr-content-text">{{ result.qr_content }}</code>
        </div>
      </div>

      <!-- QR Decoded but No Key -->
      <div v-else-if="result.qr_content && !result.key" class="result-card info">
        <div class="result-header">
          <span class="result-icon">{{ result.waf_blocked ? '🛡️' : 'ℹ️' }}</span>
          <h3>{{ result.waf_blocked ? '云安全拦截 / WAF Blocked' : '二维码已解码' }}</h3>
        </div>
        <div class="form-group">
          <span class="meta-label">二维码内容:</span>
          <div class="key-value-row">
            <code class="qr-content-text">{{ result.qr_content }}</code>
            <button class="copy-btn" @click="copyKey(result.qr_content!)" :title="'复制内容'">
              {{ copied ? '✅ 已复制' : '📋 复制' }}
            </button>
          </div>
        </div>

        <!-- WAF 拦截时显示浏览器打开按钮 / Show "open in browser" button when WAF blocked -->
        <div v-if="result.waf_blocked && result.qr_content?.startsWith('http')" class="waf-actions">
          <p class="waf-tip">
            💡 <strong>推荐操作：</strong>在浏览器中直接打开此链接获取密钥。<br />
            <strong>Recommended:</strong> Open this link directly in your browser to get the key.
          </p>
          <div class="actions">
            <a
              :href="result.qr_content"
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn-primary"
              style="text-decoration: none"
            >
              🌐 在浏览器中打开链接
            </a>
            <button class="btn btn-secondary" @click="copyKey(result.qr_content!)">
              📋 复制链接
            </button>
          </div>
        </div>

        <div v-if="result.error" class="result-note" style="white-space: pre-line">
          {{ result.error }}
        </div>
        <div v-if="result.raw_response" class="raw-response">
          <details>
            <summary>查看原始响应</summary>
            <pre>{{ result.raw_response }}</pre>
          </details>
        </div>
      </div>

      <!-- Error -->
      <div v-else class="result-card error">
        <div class="result-header">
          <span class="result-icon">❌</span>
          <h3>处理失败</h3>
        </div>
        <p class="error-msg">{{ result.error }}</p>
      </div>
    </div>

    <!-- Instructions -->
    <div class="instructions card">
      <h3>�� 使用说明</h3>

      <h4>旧固件设备（&lt; 5.3.0，通常 2017 年以前出厂）</h4>
      <ol>
        <li>在 SADP 工具中找到需要重置密码的设备</li>
        <li>点击"忘记密码"，进入密码重置界面</li>
        <li>
          <strong>方式一（离线生成）：</strong> 使用"⚙️ 离线生成"选项卡 → 输入 SADP 中显示的序列号和设备内部日期（重启设备后查看 Start Time 列）→ 生成安全码
        </li>
        <li>
          <strong>方式二（二维码截图）：</strong> 截图上传二维码图片，系统自动解码，尝试通过海康服务 API 获取密钥或离线计算
        </li>
        <li>将安全码输入 SADP 的安全码输入框（Serial Code / Security Code），设置新密码</li>
      </ol>

      <h4>新固件设备（≥ 5.3.0，如 v5.x / v7.x）</h4>
      <div class="note" style="margin-bottom: 12px">
        <strong>⚠️ 重要：</strong>
        新固件设备<strong>不支持离线安全码算法</strong>，必须通过海康威视官方渠道重置。
        <br />Newer firmware does <strong>NOT</strong> support the offline security code algorithm.
        You must reset through Hikvision's official channels.
      </div>
      <ol>
        <li>
          <strong>微信扫码（推荐）：</strong> 在 SADP 中选择二维码方式 → 使用微信扫描二维码 →
          进入"海康威视客户服务"公众号 → 按提示完成密码重置
        </li>
        <li>
          <strong>导出设备文件：</strong> 在 SADP 中点击"导出"→ 保存设备特征文件（.xml）→
          通过微信公众号"<strong>海康威视客户服务</strong>"的"贴心服务→密码重置"提交文件 →
          收到重置文件（Encrypt.xml）后在 SADP 中导入 → 设置新密码
        </li>
        <li>
          <strong>电话联系：</strong> 拨打海康威视技术支持热线 <strong>400-700-5998</strong>，
          提供设备序列号和导出的设备特征文件
        </li>
        <li>
          <strong>Hik-Connect / 萤石云：</strong> 如果设备已绑定 Hik-Connect 或萤石云账号，
          可通过 APP 的"忘记密码"功能直接重置
        </li>
        <li>
          <strong>GUID 文件：</strong> 如果初始激活时保存了 GUID 文件，可在 SADP 中直接导入重置
        </li>
      </ol>

      <div class="note">
        <strong>⚠️ 注意：</strong>
        离线算法基于序列号和设备日期生成安全码，<strong>仅适用于旧固件设备（&lt; 5.3.0）</strong>。
        新固件设备的所有密码重置均需通过海康威视官方服务器验证，无法本地生成。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface KeyResponse {
  key: string | null
  qr_content: string | null
  method: string | null
  error: string | null
  raw_response: string | null
  waf_blocked: boolean
}

// In dev, Vite proxies /api to the backend. In prod, set VITE_API_BASE_URL to empty string or backend URL.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

const tabs = [
  { id: 'qr', label: '📷 上传二维码' },
  { id: 'offline', label: '⚙️ 离线生成' },
]
const activeTab = ref('qr')
const isLoading = ref(false)
const result = ref<KeyResponse | null>(null)
const copied = ref(false)

// QR Upload tab
const selectedFile = ref<File | null>(null)
const previewUrl = ref<string | null>(null)
const isDragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// Offline tab
const offlineSerial = ref('')
const offlineDate = ref((() => {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
})())

// ─── File upload ─────────────────────────────────────────────────────────────

function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    setFile(input.files[0])
  }
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  const files = event.dataTransfer?.files
  if (files && files[0] && files[0].type.startsWith('image/')) {
    setFile(files[0])
  }
}

function setFile(file: File) {
  selectedFile.value = file
  result.value = null
  const reader = new FileReader()
  reader.onload = (e) => {
    previewUrl.value = e.target?.result as string
  }
  reader.readAsDataURL(file)
}

function clearImage() {
  selectedFile.value = null
  previewUrl.value = null
  result.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

// Handle paste event (Ctrl+V)
function handlePaste(event: ClipboardEvent) {
  if (activeTab.value !== 'qr') return
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        setFile(file)
        break
      }
    }
  }
}

onMounted(() => {
  window.addEventListener('paste', handlePaste)
})

onUnmounted(() => {
  window.removeEventListener('paste', handlePaste)
})

// ─── API calls ───────────────────────────────────────────────────────────────

async function uploadQrImage() {
  if (!selectedFile.value) return
  isLoading.value = true
  result.value = null
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const response = await fetch(`${API_BASE}/api/qr/upload`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      const err = await response.json()
      result.value = { key: null, qr_content: null, method: null, error: err.detail || '上传失败', raw_response: null, waf_blocked: false }
      return
    }
    result.value = await response.json()
  } catch (e) {
    result.value = { key: null, qr_content: null, method: null, error: `网络错误: ${e}`, raw_response: null, waf_blocked: false }
  } finally {
    isLoading.value = false
  }
}

async function generateOfflineKey() {
  if (!offlineSerial.value.trim() || !offlineDate.value) return
  isLoading.value = true
  result.value = null
  try {
    const response = await fetch(`${API_BASE}/api/key/offline`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: offlineSerial.value, date: offlineDate.value }),
    })
    if (!response.ok) {
      const err = await response.json()
      result.value = { key: null, qr_content: null, method: null, error: err.detail || '生成失败', raw_response: null, waf_blocked: false }
      return
    }
    result.value = await response.json()
  } catch (e) {
    result.value = { key: null, qr_content: null, method: null, error: `网络错误: ${e}`, raw_response: null, waf_blocked: false }
  } finally {
    isLoading.value = false
  }
}

// ─── Utilities ───────────────────────────────────────────────────────────────

async function copyKey(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // Fallback
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  }
}

function methodLabel(method: string): string {
  const labels: Record<string, string> = {
    offline_v1: '离线算法（序列号+日期，仅旧固件 < 5.3.0）',
    offline_from_url: '离线算法（从 URL 提取，仅旧固件 < 5.3.0）',
    url_fetch: '在线获取（通过服务器）',
    url_fetch_via_redirect: '在线获取（通过重定向）',
    hikvision_service_api: '海康服务 API（自动提交）',
    raw: '原始内容',
  }
  return labels[method] || method
}
</script>

<style scoped>
.reset-tool {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tab-btn {
  padding: 10px 20px;
  border: 2px solid #d32f2f;
  border-radius: 8px;
  background: white;
  color: #d32f2f;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 500;
}

.tab-btn:hover {
  background: #fce4e4;
}

.tab-btn.active {
  background: #d32f2f;
  color: white;
}

.card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.tab-content h2 {
  font-size: 1.2rem;
  margin-bottom: 8px;
  color: #333;
}

.description {
  color: #666;
  margin-bottom: 16px;
  font-size: 0.9rem;
  line-height: 1.5;
}

/* ── Upload area ── */
.upload-area {
  border: 2px dashed #ccc;
  border-radius: 12px;
  padding: 32px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  min-height: 150px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fafafa;
}

.upload-area:hover,
.upload-area.dragover {
  border-color: #d32f2f;
  background: #fce4e4;
}

.upload-area.has-image {
  padding: 12px;
  min-height: auto;
}

.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.upload-icon {
  font-size: 2.5rem;
}

.upload-placeholder p {
  color: #666;
  font-size: 0.95rem;
}

.hint {
  font-size: 0.8rem !important;
  color: #999 !important;
}

.preview-container {
  width: 100%;
}

.preview-image {
  max-width: 100%;
  max-height: 300px;
  border-radius: 8px;
  object-fit: contain;
}

.paste-hint {
  color: #888;
  font-size: 0.85rem;
  margin-top: 8px;
  text-align: center;
}

kbd {
  background: #eee;
  border: 1px solid #bbb;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.85em;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label,
.meta-label {
  display: block;
  font-weight: 600;
  margin-bottom: 6px;
  color: #444;
  font-size: 0.9rem;
}

.input,
.textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 0.95rem;
  transition: border-color 0.2s;
  font-family: inherit;
}

.input:focus,
.textarea:focus {
  outline: none;
  border-color: #d32f2f;
  box-shadow: 0 0 0 3px rgba(211, 47, 47, 0.1);
}

.actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: #d32f2f;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #b71c1c;
}

.btn-secondary {
  background: #f5f5f5;
  color: #666;
  border: 1px solid #ddd;
}

.btn-secondary:hover:not(:disabled) {
  background: #eee;
}

.spinner {
  display: inline-block;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.result-container {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.result-card {
  border-radius: 12px;
  padding: 20px;
  border: 2px solid;
}

.result-card.success {
  background: #f0fff4;
  border-color: #4caf50;
}

.result-card.error {
  background: #fff5f5;
  border-color: #f44336;
}

.result-card.info {
  background: #f0f8ff;
  border-color: #2196f3;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.result-icon {
  font-size: 1.5rem;
}

.result-header h3 {
  font-size: 1.1rem;
}

.key-display {
  background: white;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
  border: 1px solid #e8f5e9;
}

.key-label {
  display: block;
  font-weight: 600;
  font-size: 0.85rem;
  color: #555;
  margin-bottom: 8px;
}

.key-value-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.key-value {
  font-family: 'Courier New', monospace;
  font-size: 2rem;
  font-weight: bold;
  color: #1a237e;
  letter-spacing: 4px;
  background: #f8f9fa;
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #e3e8ef;
}

.copy-btn {
  padding: 8px 16px;
  background: #4caf50;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 500;
  transition: background 0.2s;
  white-space: nowrap;
}

.copy-btn:hover {
  background: #388e3c;
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: #666;
  margin-top: 8px;
}

.meta-value {
  background: #e8f5e9;
  padding: 2px 8px;
  border-radius: 4px;
  color: #2e7d32;
}

.result-note {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  background: #fff3e0;
  border: 1px solid #ffcc02;
  color: #e65100;
}

.result-note.warning {
  background: #fff8e1;
  border-color: #ffc107;
}

.result-qr-content {
  margin-top: 12px;
}

.qr-content-text {
  display: block;
  font-family: 'Courier New', monospace;
  font-size: 0.8rem;
  background: #f5f5f5;
  padding: 8px 12px;
  border-radius: 6px;
  word-break: break-all;
  color: #333;
  margin-top: 4px;
}

.error-msg {
  color: #c62828;
  font-size: 0.95rem;
}

.raw-response {
  margin-top: 12px;
}

.raw-response details {
  cursor: pointer;
}

.raw-response summary {
  color: #666;
  font-size: 0.85rem;
  font-weight: 500;
}

.raw-response pre {
  margin-top: 8px;
  padding: 12px;
  background: #f5f5f5;
  border-radius: 6px;
  font-size: 0.75rem;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.instructions {
  background: #fff9f0;
  border: 1px solid #ffe0b2;
}

.instructions h3 {
  margin-bottom: 12px;
  color: #e65100;
  font-size: 1rem;
}

.instructions ol {
  padding-left: 20px;
  line-height: 1.8;
  font-size: 0.9rem;
  color: #555;
}

.instructions .note {
  margin-top: 12px;
  padding: 10px;
  background: #fff3e0;
  border-radius: 6px;
  font-size: 0.85rem;
  color: #e65100;
  line-height: 1.5;
}

.instructions h4 {
  font-size: 0.95rem;
  color: #d32f2f;
  margin-top: 16px;
  margin-bottom: 8px;
}

/* ── Firmware version warning ── */
.firmware-warning {
  margin-bottom: 16px;
  padding: 12px 16px;
  background: #fff3e0;
  border: 2px solid #ff9800;
  border-radius: 8px;
  font-size: 0.85rem;
  color: #e65100;
  line-height: 1.6;
}

.firmware-warning ul {
  margin: 6px 0 0 0;
  padding-left: 20px;
}

.firmware-warning li {
  margin-bottom: 4px;
}

/* ─── WAF block styles ──────────────────────────────────────────────────── */

.waf-actions {
  margin: 12px 0;
  padding: 16px;
  background: #e3f2fd;
  border: 2px solid #1976d2;
  border-radius: 8px;
}

.waf-tip {
  margin-bottom: 12px;
  color: #0d47a1;
  font-size: 0.9rem;
  line-height: 1.5;
}
</style>
