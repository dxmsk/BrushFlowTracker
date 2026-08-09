<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  initialTab: { type: String, default: 'tasks' },
  compact: { type: Boolean, default: false },
  showClose: { type: Boolean, default: false },
})
const emit = defineEmits(['action', 'close'])
const hostToast = inject('moviepilot:toast', null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const activeTab = ref(props.initialTab)
const selectedSiteId = ref('')
const deleteSiteDialog = ref(false)
const status = ref({ settings: { sites: [] }, sites: [], tasks: [], history: [], downloaders: [] })
const draft = ref({ sites: [] })

const pluginBase = 'plugin/BrushFlowTracker'
const sites = computed(() => draft.value.sites || [])
const selectedSite = computed(() => sites.value.find(site => site.id === selectedSiteId.value) || null)
const selectedSummary = computed(() => status.value.sites?.find(site => site.id === selectedSiteId.value) || {})

const resolutionOptions = ['8K', '4K', '1080P', '1080I', '720P', '576P', '480P']
const promotionOptions = [
  { title: '不限促销', value: 'any' },
  { title: '仅免费', value: 'free' },
  { title: '免费或双倍上传免费', value: 'free_or_2xfree' },
  { title: '仅双倍上传免费', value: '2xfree' },
]
const taskHeaders = [
  { title: '任务', key: 'name', sortable: false },
  { title: '进度', key: 'progress', sortable: false },
  { title: '状态', key: 'state', sortable: false },
  { title: '分享率', key: 'ratio', sortable: false },
  { title: '速度', key: 'speed', sortable: false },
  { title: '免费截止', key: 'free_until', sortable: false },
]

function unwrap(response) {
  if (response?.success === false) throw new Error(response.message || '操作失败')
  return response?.data ?? response
}

function notify(message, kind = 'success') {
  if (typeof hostToast?.[kind] === 'function') hostToast[kind](message)
  else if (kind === 'error') error.value = message
}

function uid() {
  return globalThis.crypto?.randomUUID?.().replaceAll('-', '') || `${Date.now()}${Math.random()}`.replace('.', '')
}

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

async function loadStatus(preserveDraft = false) {
  loading.value = true
  error.value = ''
  try {
    const query = selectedSiteId.value ? `?site_id=${encodeURIComponent(selectedSiteId.value)}` : ''
    status.value = unwrap(await props.api.get(`${pluginBase}/status${query}`))
    if (!preserveDraft) draft.value = clone(status.value.settings || { sites: [] })
    const exists = sites.value.some(site => site.id === selectedSiteId.value)
    if (!exists) selectedSiteId.value = sites.value[0]?.id || ''
  } catch (err) {
    error.value = err?.message || '加载刷流追新失败'
  } finally {
    loading.value = false
  }
}

async function selectSite(siteId) {
  selectedSiteId.value = siteId
  await loadStatus(true)
}

function addSite() {
  const id = uid()
  sites.value.push({
    id,
    name: `站点 ${sites.value.length + 1}`,
    enabled: true,
    use_proxy: false,
    user_agent: '',
    rss_rules: [],
    cleanup_rules: [],
  })
  selectedSiteId.value = id
  activeTab.value = 'rss'
}

function confirmDeleteSite() {
  const index = sites.value.findIndex(site => site.id === selectedSiteId.value)
  if (index >= 0) sites.value.splice(index, 1)
  selectedSiteId.value = sites.value[Math.min(index, sites.value.length - 1)]?.id || ''
  deleteSiteDialog.value = false
}

function addRssRule() {
  selectedSite.value.rss_rules.push({
    id: uid(), name: `RSS 规则 ${selectedSite.value.rss_rules.length + 1}`, enabled: true, url: '',
    required_keywords: [], excluded_keywords: [], resolutions: [], max_age_minutes: null,
    min_size_gib: null, promotion: 'any', tags: [],
  })
}

function addCleanupRule() {
  selectedSite.value.cleanup_rules.push({
    id: uid(), name: `删种规则 ${selectedSite.value.cleanup_rules.length + 1}`, enabled: true,
    labels: [], min_seed_hours: 0, min_ratio: 0, delete_files: false,
  })
}

function removeRule(collection, index) {
  collection.splice(index, 1)
}

function moveRule(collection, index, offset) {
  const target = index + offset
  if (target < 0 || target >= collection.length) return
  const [rule] = collection.splice(index, 1)
  collection.splice(target, 0, rule)
}

async function saveSettings() {
  saving.value = true
  try {
    status.value = unwrap(await props.api.post(`${pluginBase}/settings`, draft.value))
    draft.value = clone(status.value.settings)
    await loadStatus(true)
    notify('配置已保存，定时任务已更新')
    emit('action')
  } catch (err) {
    notify(err?.message || '保存配置失败', 'error')
  } finally {
    saving.value = false
  }
}

async function runOperation(operation) {
  saving.value = true
  try {
    unwrap(await props.api.post(`${pluginBase}/run`, { operation, site_id: selectedSiteId.value || null }))
    notify('任务已提交到后台')
  } catch (err) {
    notify(err?.message || '提交任务失败', 'error')
  } finally {
    saving.value = false
  }
}

async function testDownloader() {
  saving.value = true
  try {
    const data = unwrap(await props.api.post(`${pluginBase}/test-downloader`, { downloader: draft.value.downloader || '' }))
    notify(`连接正常，当前 ${data.torrent_count} 个任务`)
  } catch (err) {
    notify(err?.message || 'qBittorrent 连接失败', 'error')
  } finally {
    saving.value = false
  }
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function formatDuration(seconds) {
  const hours = Math.floor(Number(seconds || 0) / 3600)
  if (hours >= 24) return `${Math.floor(hours / 24)} 天 ${hours % 24} 小时`
  return `${hours} 小时`
}

watch(() => props.initialTab, value => { if (value) activeTab.value = value })
onMounted(() => loadStatus())
</script>

<template>
  <div class="tracker" :class="{ 'tracker--compact': compact }">
    <header class="tracker__header">
      <div class="tracker__identity">
        <VIcon icon="mdi-rss-box" color="primary" size="30" />
        <div><h1>刷流追新</h1><p>一个 qBittorrent，统一托管多站点任务</p></div>
      </div>
      <div class="tracker__actions">
        <VTooltip text="刷新数据"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-refresh" variant="text" :loading="loading" @click="loadStatus()" /></template></VTooltip>
        <VBtn color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" @click="saveSettings">保存</VBtn>
        <VTooltip v-if="showClose" text="关闭"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-close" variant="text" @click="$emit('close')" /></template></VTooltip>
      </div>
    </header>

    <VAlert v-if="error" type="error" variant="tonal" closable @click:close="error = ''">{{ error }}</VAlert>
    <VAlert v-if="status.downloader_error" type="warning" variant="tonal">{{ status.downloader_error }}</VAlert>

    <div v-if="loading && !sites.length" class="tracker__loading"><VSkeletonLoader type="list-item-three-line, article" /></div>
    <div v-else class="tracker__layout">
      <VSheet tag="aside" class="site-rail app-surface-static">
        <div class="site-rail__head"><strong>站点</strong><VTooltip text="新增站点"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-plus" size="small" variant="text" @click="addSite" /></template></VTooltip></div>
        <div class="site-list">
          <button v-for="site in sites" :key="site.id" type="button" class="site-item" :class="{ 'site-item--active': site.id === selectedSiteId }" @click="selectSite(site.id)">
            <span><i :class="{ online: site.enabled }" />{{ site.name || '未命名站点' }}</span>
            <small>{{ site.rss_rules.length }} 条 RSS · {{ site.cleanup_rules.length }} 条删种</small>
          </button>
        </div>
        <VBtn block variant="tonal" prepend-icon="mdi-plus" @click="addSite">新增站点</VBtn>
      </VSheet>

      <main class="workspace">
        <VSelect class="mobile-site" :model-value="selectedSiteId" :items="sites" item-title="name" item-value="id" label="当前站点" hide-details @update:model-value="selectSite" />

        <template v-if="selectedSite">
          <div class="site-head">
            <div class="site-head__name">
              <VTextField v-model="selectedSite.name" variant="plain" density="compact" hide-details aria-label="站点名称" />
              <VChip :color="selectedSite.enabled ? 'success' : 'default'" size="small" variant="tonal">{{ selectedSite.enabled ? '启用' : '停用' }}</VChip>
            </div>
            <div class="site-head__actions">
              <VSwitch v-model="selectedSite.enabled" label="启用站点" hide-details color="success" inset />
              <VTooltip text="删除站点"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-delete-outline" color="error" variant="text" @click="deleteSiteDialog = true" /></template></VTooltip>
            </div>
          </div>

          <VTabs v-model="activeTab" class="tracker-tabs" show-arrows>
            <VTab value="tasks" prepend-icon="mdi-download-network-outline">任务</VTab>
            <VTab value="rss" prepend-icon="mdi-rss">RSS 规则</VTab>
            <VTab value="cleanup" prepend-icon="mdi-broom">删种规则</VTab>
            <VTab value="history" prepend-icon="mdi-history">记录</VTab>
            <VTab value="settings" prepend-icon="mdi-tune-variant">全局设置</VTab>
          </VTabs>

          <VWindow v-model="activeTab" class="tracker-window">
            <VWindowItem value="tasks">
              <div class="stats">
                <VSheet class="stat app-surface-static"><span>托管任务</span><strong>{{ selectedSummary.managed_count || 0 }}</strong><VIcon icon="mdi-download-circle-outline" color="primary" /></VSheet>
                <VSheet class="stat app-surface-static"><span>RSS 规则</span><strong>{{ selectedSite.rss_rules.length }}</strong><VIcon icon="mdi-rss" color="info" /></VSheet>
                <VSheet class="stat app-surface-static"><span>最近读取</span><strong>{{ selectedSummary.stats?.fetched || 0 }}</strong><VIcon icon="mdi-text-box-search-outline" color="warning" /></VSheet>
                <VSheet class="stat app-surface-static"><span>最近添加</span><strong>{{ selectedSummary.stats?.added || 0 }}</strong><VIcon icon="mdi-check-circle-outline" color="success" /></VSheet>
              </div>
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>qBittorrent 任务</h2><p>{{ draft.downloader || '尚未选择下载器' }}</p></div><div><VBtn variant="tonal" prepend-icon="mdi-rss" :loading="saving" @click="runOperation('rss')">立即刷新</VBtn><VBtn variant="text" prepend-icon="mdi-broom" :loading="saving" @click="runOperation('cleanup')">检查删种</VBtn></div></header>
                <VDataTable :headers="taskHeaders" :items="status.tasks || []" :loading="loading" density="comfortable" class="task-table">
                  <template #item.name="{ item }"><div class="task-name"><strong>{{ item.name }}</strong><small>{{ formatBytes(item.size) }} · {{ item.tags.join(', ') }}</small></div></template>
                  <template #item.progress="{ item }"><div class="progress-cell"><span>{{ item.progress }}%</span><VProgressLinear :model-value="item.progress" height="5" rounded color="primary" /></div></template>
                  <template #item.ratio="{ item }">{{ Number(item.ratio || 0).toFixed(2) }}<small class="block-muted">{{ formatDuration(item.seeding_time) }}</small></template>
                  <template #item.speed="{ item }"><span>↓ {{ formatBytes(item.dlspeed) }}/s</span><small class="block-muted">↑ {{ formatBytes(item.upspeed) }}/s</small></template>
                  <template #item.free_until="{ item }"><span :class="{ 'text-warning': item.free_until }">{{ formatTime(item.free_until) }}</span></template>
                  <template #no-data><div class="empty-table">当前站点没有托管任务</div></template>
                </VDataTable>
              </VSheet>
            </VWindowItem>

            <VWindowItem value="rss">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>RSS 选种规则</h2><p>规则未选择分辨率时才参与全局最高画质去重</p></div><VBtn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="addRssRule">新增规则</VBtn></header>
                <div v-if="!selectedSite.rss_rules.length" class="empty-state"><VIcon icon="mdi-rss-off" size="46" /><strong>尚未配置 RSS</strong><VBtn variant="tonal" @click="addRssRule">新增规则</VBtn></div>
                <VExpansionPanels v-else multiple variant="accordion" class="rule-list">
                  <VExpansionPanel v-for="(rule, index) in selectedSite.rss_rules" :key="rule.id">
                    <VExpansionPanelTitle><div class="rule-title"><VIcon icon="mdi-rss" color="info" /><strong>{{ rule.name || `RSS 规则 ${index + 1}` }}</strong><VChip size="x-small" :color="rule.enabled ? 'success' : 'default'" variant="tonal">{{ rule.enabled ? '启用' : '停用' }}</VChip></div></VExpansionPanelTitle>
                    <VExpansionPanelText>
                      <div class="rule-grid">
                        <VTextField v-model="rule.name" label="规则名称" hide-details />
                        <VSwitch v-model="rule.enabled" label="启用规则" hide-details color="success" inset />
                        <VTextField v-model="rule.url" class="span-2" label="RSS 订阅地址" placeholder="https://tracker.example/torrentrss.php?..." hide-details />
                        <VCombobox v-model="rule.required_keywords" label="必须包含关键词" multiple chips closable-chips hide-details />
                        <VCombobox v-model="rule.excluded_keywords" label="排除关键词" multiple chips closable-chips hide-details />
                        <VSelect v-model="rule.resolutions" :items="resolutionOptions" label="分辨率筛选" multiple chips closable-chips clearable hide-details />
                        <VSelect v-model="rule.promotion" :items="promotionOptions" label="免费期筛选" hide-details />
                        <VTextField v-model.number="rule.max_age_minutes" type="number" min="0" label="最大发种时间（分钟）" clearable hide-details />
                        <VTextField v-model.number="rule.min_size_gib" type="number" min="0" step="0.1" label="最小文件大小（GiB）" clearable hide-details />
                        <VCombobox v-model="rule.tags" class="span-2" label="自动添加标签" multiple chips closable-chips hide-details />
                      </div>
                      <div class="rule-actions"><VTooltip text="上移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-up" size="small" variant="text" :disabled="index === 0" @click="moveRule(selectedSite.rss_rules, index, -1)" /></template></VTooltip><VTooltip text="下移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-down" size="small" variant="text" :disabled="index === selectedSite.rss_rules.length - 1" @click="moveRule(selectedSite.rss_rules, index, 1)" /></template></VTooltip><VSpacer /><VBtn color="error" variant="text" prepend-icon="mdi-delete-outline" @click="removeRule(selectedSite.rss_rules, index)">删除</VBtn></div>
                    </VExpansionPanelText>
                  </VExpansionPanel>
                </VExpansionPanels>
              </VSheet>
            </VWindowItem>

            <VWindowItem value="cleanup">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>顺序删种规则</h2><p>每个任务只执行第一条标签与阈值均命中的规则</p></div><VBtn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="addCleanupRule">新增规则</VBtn></header>
                <div v-if="!selectedSite.cleanup_rules.length" class="empty-state"><VIcon icon="mdi-broom" size="46" /><strong>尚未配置自动删种</strong><VBtn variant="tonal" @click="addCleanupRule">新增规则</VBtn></div>
                <div v-else class="cleanup-list">
                  <VSheet v-for="(rule, index) in selectedSite.cleanup_rules" :key="rule.id" class="cleanup-rule">
                    <div class="order">{{ index + 1 }}</div>
                    <div class="cleanup-fields">
                      <VTextField v-model="rule.name" label="规则名称" hide-details />
                      <VCombobox v-model="rule.labels" label="适用标签（全部匹配）" multiple chips closable-chips hide-details />
                      <VTextField v-model.number="rule.min_seed_hours" type="number" min="0" step="0.5" label="最小做种时间（小时）" hide-details />
                      <VTextField v-model.number="rule.min_ratio" type="number" min="0" step="0.1" label="最小分享率" hide-details />
                      <VSwitch v-model="rule.enabled" label="启用" hide-details color="success" inset />
                      <VSwitch v-model="rule.delete_files" label="同时删除文件" hide-details color="error" inset />
                    </div>
                    <div class="vertical-actions"><VTooltip text="上移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-up" size="small" variant="text" :disabled="index === 0" @click="moveRule(selectedSite.cleanup_rules, index, -1)" /></template></VTooltip><VTooltip text="下移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-down" size="small" variant="text" :disabled="index === selectedSite.cleanup_rules.length - 1" @click="moveRule(selectedSite.cleanup_rules, index, 1)" /></template></VTooltip><VTooltip text="删除"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-delete-outline" size="small" color="error" variant="text" @click="removeRule(selectedSite.cleanup_rules, index)" /></template></VTooltip></div>
                  </VSheet>
                </div>
              </VSheet>
            </VWindowItem>

            <VWindowItem value="history">
              <VSheet class="panel app-surface-static"><header class="panel__head"><div><h2>处理记录</h2><p>最近 100 条添加与删除结果</p></div></header><div class="history-list"><article v-for="row in status.history || []" :key="`${row.time}-${row.title}`"><VIcon :icon="row.event === 'added' ? 'mdi-download-circle-outline' : 'mdi-delete-circle-outline'" :color="row.event === 'added' ? 'success' : 'warning'" /><div><strong>{{ row.title }}</strong><span>{{ row.reason || `${row.rule_name || 'RSS 规则'} · ${row.resolution || '未知画质'}` }}</span></div><time>{{ formatTime(row.time) }}</time></article><div v-if="!status.history?.length" class="empty-table">暂无处理记录</div></div></VSheet>
            </VWindowItem>

            <VWindowItem value="settings">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>全局连接与调度</h2><p>所有站点共用这一项 qBittorrent 配置</p></div></header>
                <div class="settings-grid">
                  <VSwitch v-model="draft.enabled" label="启用插件" color="success" hide-details inset />
                  <VSwitch v-model="draft.show_sidebar_nav" label="显示侧栏入口" hide-details inset />
                  <VSelect v-model="draft.downloader" class="span-2" :items="status.downloaders" label="qBittorrent 下载器" placeholder="选择 MoviePilot 中已配置的 qBittorrent" hide-details><template #append><VTooltip text="测试连接"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-connection" variant="text" :loading="saving" @click="testDownloader" /></template></VTooltip></template></VSelect>
                  <VSwitch v-model="draft.highest_resolution_dedup" class="span-2" label="同一影视仅下载最高分辨率" color="primary" hide-details inset />
                  <VTextField v-model.number="draft.rss_interval_minutes" type="number" min="1" label="RSS 刷新间隔（分钟）" hide-details />
                  <VTextField v-model.number="draft.free_monitor_interval_minutes" type="number" min="1" label="免费期检查间隔（分钟）" hide-details />
                  <VTextField v-model.number="draft.cleanup_interval_minutes" type="number" min="1" label="自动删种间隔（分钟）" hide-details />
                  <VTextField v-model.number="draft.request_timeout_seconds" type="number" min="5" max="120" label="RSS 请求超时（秒）" hide-details />
                  <VTextField v-model.number="draft.history_limit" type="number" min="50" max="5000" label="历史记录上限" hide-details />
                  <VSwitch v-model="selectedSite.use_proxy" label="当前站点 RSS 使用代理" hide-details inset />
                  <VTextField v-model="selectedSite.user_agent" class="span-2" label="当前站点自定义 User-Agent" clearable hide-details />
                </div>
                <div class="settings-actions"><VBtn color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" @click="saveSettings">保存全部设置</VBtn><VBtn variant="tonal" prepend-icon="mdi-timer-refresh-outline" :loading="saving" @click="runOperation('free_monitor')">检查免费期</VBtn></div>
              </VSheet>
            </VWindowItem>
          </VWindow>
        </template>

        <div v-else class="empty-state empty-workspace"><VIcon icon="mdi-web-off" size="56" /><strong>还没有站点</strong><VBtn color="primary" variant="flat" prepend-icon="mdi-plus" @click="addSite">创建第一个站点</VBtn></div>
      </main>
    </div>

    <VDialog v-model="deleteSiteDialog" max-width="28rem"><VCard title="删除站点"><VCardText>删除“{{ selectedSite?.name }}”及其所有规则？下载器中的现有任务不会被删除。</VCardText><VCardActions><VSpacer /><VBtn variant="text" @click="deleteSiteDialog = false">取消</VBtn><VBtn color="error" variant="flat" @click="confirmDeleteSite">删除</VBtn></VCardActions></VCard></VDialog>
  </div>
</template>

<style scoped>
.tracker { display: flex; flex-direction: column; gap: 16px; min-inline-size: 0; padding: 16px; }
.tracker--compact { padding: 20px; }
.tracker__header, .tracker__identity, .tracker__actions, .site-rail__head, .site-head, .site-head__name, .site-head__actions, .panel__head, .panel__head > div:last-child, .rule-title, .rule-actions { display: flex; align-items: center; }
.tracker__header, .site-rail__head, .site-head, .panel__head { justify-content: space-between; gap: 12px; }
.tracker__identity { gap: 12px; min-inline-size: 0; }
.tracker__identity h1, .panel h2 { margin: 0; font-size: 1.25rem; line-height: 1.35; letter-spacing: 0; }
.tracker__identity p, .panel__head p { margin: 2px 0 0; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: .85rem; }
.tracker__actions, .site-head__actions, .panel__head > div:last-child, .rule-title, .rule-actions { gap: 8px; }
.tracker__loading, .empty-workspace { min-block-size: 24rem; }
.tracker__layout { display: grid; grid-template-columns: minmax(14rem, .3fr) minmax(0, 1.7fr); align-items: start; gap: 18px; }
.site-rail { position: sticky; top: 76px; display: flex; flex-direction: column; gap: 10px; max-block-size: calc(100dvh - 100px); padding: 12px; border: var(--app-surface-border); border-radius: var(--app-surface-radius); }
.site-list { display: flex; flex-direction: column; gap: 5px; overflow-y: auto; }
.site-item { display: flex; flex-direction: column; gap: 5px; inline-size: 100%; padding: 11px 12px; border: 1px solid transparent; border-radius: var(--app-control-radius); color: inherit; background: transparent; font: inherit; text-align: start; cursor: pointer; }
.site-item:hover { background: rgba(var(--v-theme-primary), .05); }
.site-item--active { border-color: rgba(var(--v-theme-primary), .3); background: rgba(var(--v-theme-primary), .1); }
.site-item span { display: flex; align-items: center; gap: 8px; overflow-wrap: anywhere; }
.site-item i { inline-size: 8px; block-size: 8px; flex: 0 0 auto; border-radius: 50%; background: rgb(var(--v-theme-secondary)); }
.site-item i.online { background: rgb(var(--v-theme-success)); }
.site-item small, .block-muted, .task-name small { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.workspace { min-inline-size: 0; }
.mobile-site { display: none; }
.site-head { min-block-size: 52px; }
.site-head__name { flex: 1 1 auto; gap: 8px; min-inline-size: 0; }
.site-head__name :deep(.v-field__input) { min-block-size: 40px; padding: 0; font-size: 1.2rem; font-weight: 600; }
.tracker-tabs { max-inline-size: 100%; }
.tracker-window { padding-block-start: 16px; }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-block-end: 12px; }
.stat { position: relative; display: flex; flex-direction: column; gap: 4px; min-block-size: 104px; padding: 16px; border: var(--app-surface-border); border-radius: var(--app-surface-radius); }
.stat span { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.stat strong { font-size: 1.45rem; }
.stat > :deep(.v-icon) { position: absolute; inset: 18px 16px auto auto; }
.panel { min-inline-size: 0; padding: 16px; border: var(--app-surface-border); border-radius: var(--app-surface-radius); }
.panel__head { align-items: flex-start; margin-block-end: 16px; }
.task-table { background: transparent; }
.task-name { display: flex; flex-direction: column; max-inline-size: 30rem; }
.task-name strong, .task-name small { overflow-wrap: anywhere; }
.progress-cell { display: grid; grid-template-columns: 3.2rem 7rem; align-items: center; gap: 8px; }
.block-muted { display: block; font-size: .78rem; }
.empty-table { padding: 28px 12px; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); text-align: center; }
.empty-state { display: grid; place-items: center; align-content: center; gap: 12px; min-block-size: 18rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.rule-list { margin-block-start: 8px; }
.rule-title { min-inline-size: 0; flex-wrap: wrap; }
.rule-title strong { overflow-wrap: anywhere; }
.rule-grid, .settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding-block: 8px; }
.span-2 { grid-column: 1 / -1; }
.rule-actions { margin-block-start: 12px; }
.cleanup-list { display: flex; flex-direction: column; gap: 10px; }
.cleanup-rule { display: grid; grid-template-columns: 32px minmax(0, 1fr) 36px; align-items: center; gap: 12px; padding: 14px; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: var(--app-control-radius); }
.order { display: grid; place-items: center; inline-size: 28px; block-size: 28px; border-radius: 50%; color: rgb(var(--v-theme-on-primary)); background: rgb(var(--v-theme-primary)); font-size: .8rem; }
.cleanup-fields { display: grid; grid-template-columns: 1.1fr 1.5fr repeat(2, minmax(9rem, .7fr)) auto auto; align-items: center; gap: 10px; min-inline-size: 0; }
.vertical-actions { display: flex; flex-direction: column; gap: 2px; }
.history-list { display: flex; flex-direction: column; }
.history-list article { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 12px; padding: 12px 4px; border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.history-list article > div { display: flex; flex-direction: column; min-inline-size: 0; }
.history-list article strong, .history-list article span { overflow-wrap: anywhere; }
.history-list article span, .history-list time { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: .8rem; }
.settings-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-block-start: 18px; }
@media (max-width: 1199px) { .cleanup-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (min-width: 960px) { .tracker--compact { block-size: calc(100dvh - 48px); min-block-size: 0; overflow: hidden; } .tracker--compact .tracker__layout { flex: 1 1 auto; min-block-size: 0; overflow: hidden; } .tracker--compact .site-rail { position: static; block-size: 100%; max-block-size: none; } .tracker--compact .workspace { block-size: 100%; padding-inline-end: 4px; overflow-y: auto; } }
@media (max-width: 959px) { .tracker { padding: 12px; } .site-rail { display: none; } .mobile-site { display: block; margin-block-end: 12px; } .tracker__layout { grid-template-columns: 1fr; } .rule-grid, .settings-grid { grid-template-columns: 1fr; } .span-2 { grid-column: auto; } }
@media (max-width: 699px) { .tracker__identity p, .tracker__actions > :deep(.v-btn:first-child) { display: none; } .tracker__actions { flex-wrap: nowrap; } .site-head { align-items: flex-start; flex-direction: column; } .site-head__actions { inline-size: 100%; justify-content: space-between; } .panel__head { flex-direction: column; } .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .task-table { font-size: .8rem; } .cleanup-rule { grid-template-columns: 28px minmax(0, 1fr); } .vertical-actions { grid-column: 2; flex-direction: row; } .cleanup-fields { grid-template-columns: 1fr; } .history-list article { grid-template-columns: auto minmax(0, 1fr); } .history-list time { grid-column: 2; } }
</style>
