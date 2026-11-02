<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import TaskTitle from './TaskTitle.vue'
import {
  clone, fingerprint, uid, unwrap, requestGate, prepareSettings, saveResolution,
  removeRssAndDisableReferences, operationNames, proxyOptions, promotionOptions,
  timeUnitOptions, sizeUnitOptions, resolutionOptions, formatBytes, formatTime,
  formatDuration, taskTags, taskProgress, taskState, pauseExplanation, freeRemaining,
  ruleSummary, normalizeJobs, reconcileJobs, validateSettings,
} from '../utils/workbench.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  initialTab: { type: String, default: 'tasks' },
  compact: { type: Boolean, default: false },
  showClose: { type: Boolean, default: false },
})
const emit = defineEmits(['action', 'close'])
const hostToast = inject('moviepilot:toast', null)
const loading = ref(true)
const tasksLoading = ref(false)
const saving = ref(false)
const testing = ref(false)
const runSubmitting = ref({})
const pendingJobs = ref({})
const settingsLoaded = ref(false)
const statusError = ref('')
const error = ref('')
const message = ref('')
const messageKind = ref('success')
const messageOpen = ref(false)
const referenceWarning = ref('')
const pollWarning = ref('')
const lastSynced = ref(null)
const now = ref(Date.now())
const settingsForm = ref(null)
const activeTab = ref(props.initialTab)
const selectedSiteId = ref('')
const deleteSiteDialog = ref(false)
const discardDialog = ref(false)
const leaveDialog = ref(false)
const cleanupDialog = ref(false)
const cleanupTarget = ref(null)
const authRuleId = ref(null)
const status = ref({ settings: { sites: [] }, sites: [], tasks: [], history: [], downloaders: [], running_jobs: {} })
const draft = ref({ sites: [] })
const savedSettings = ref({ sites: [] })
const draftRevision = ref(0)
const statusGate = requestGate()
const tasksGate = requestGate()
let configEpoch = 0
let replacingDraft = false
let mounted = false
let disposed = false
let pollTimer = null
let clockTimer = null
let pollDeadline = 0
let pollFailures = 0
let lastTaskPoll = 0
const POLL_BUDGET = 15 * 60 * 1000

const pluginBase = 'plugin/BrushFlowTracker'
const sites = computed(() => draft.value.sites || [])
const selectedSite = computed(() => sites.value.find(site => site.id === selectedSiteId.value) || null)
const savedSite = computed(() => savedSettings.value.sites?.find(site => site.id === selectedSiteId.value) || null)
const selectedSummary = computed(() => status.value.sites?.find(site => site.id === selectedSiteId.value) || {})
const authRule = computed(() => selectedSite.value?.rss_rules?.find(rule => rule.id === authRuleId.value) || null)
const authDialog = computed({
  get: () => Boolean(authRule.value),
  set: value => { if (!value) authRuleId.value = null },
})
const taskNameOptions = computed(() => selectedSite.value?.rss_rules?.map(rule => rule.name).filter(Boolean) || [])
const dirty = computed(() => settingsLoaded.value && fingerprint(draft.value) !== fingerprint(savedSettings.value))
const canSave = computed(() => settingsLoaded.value && !statusError.value && !loading.value && !saving.value && dirty.value)
const runDisabledReason = computed(() => {
  if (!settingsLoaded.value || statusError.value) return '配置未成功加载，暂不能执行'
  if (saving.value) return '正在保存，请等待保存完成'
  if (dirty.value) return '有未保存修改，请先保存；手动运行只使用服务器已保存配置'
  if (status.value.config_pending) return '设置已保存，将在当前后台任务结束后生效'
  if (Object.keys(status.value.running_jobs || {}).length) return '已有后台任务正在执行，请等待本轮完成'
  if (!savedSite.value) return '请先创建并保存站点'
  return ''
})
const jobs = computed(() => normalizeJobs(status.value.running_jobs))
const jobRows = computed(() => Object.entries({ ...pendingJobs.value, ...jobs.value }).map(([operation, job]) => ({
  ...job, operation,
  name: operationNames[operation] || operation,
  siteName: job.site_id ? savedSettings.value.sites?.find(site => site.id === job.site_id)?.name || '其他站点' : '全部站点',
  pending: !jobs.value[operation],
})))
const downloaderLabel = computed(() => savedSettings.value.downloader_mode === 'custom'
  ? (savedSettings.value.custom_qb_url || '自定义 qBittorrent')
  : (savedSettings.value.downloader || '尚未选择下载器'))
const taskSearch = ref('')
const taskStateFilter = ref('all')
const taskRuleFilter = ref(null)
const taskPage = ref(1)
const taskPageSize = ref(10)
const historySearch = ref('')
const historyFilter = ref('all')
const historyPage = ref(1)
const historyPageSize = ref(20)
const stateOptions = [
  { title: '全部状态', value: 'all' }, { title: '下载中', value: 'downloading' },
  { title: '做种中', value: 'seeding' }, { title: '已暂停', value: 'paused' },
  { title: '排队中', value: 'queued' }, { title: '校验 / 移动', value: 'checking' },
  { title: '任务错误', value: 'error' }, { title: '其他状态', value: 'other' },
]
const taskFilterOptions = computed(() => [...new Set([...(savedSite.value?.rss_rules || []).map(rule => rule.name), ...(status.value.tasks || []).flatMap(taskTags)])].filter(Boolean))
const filteredTasks = computed(() => (status.value.tasks || []).filter(item => {
  const query = taskSearch.value.trim().toLocaleLowerCase()
  return (!query || `${item.name || ''} ${taskTags(item).join(' ')} ${item.hash || ''}`.toLocaleLowerCase().includes(query))
    && (taskStateFilter.value === 'all' || taskState(item).key === taskStateFilter.value)
    && (!taskRuleFilter.value || taskTags(item).includes(taskRuleFilter.value))
}))
const taskPageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / taskPageSize.value)))
const pagedTasks = computed(() => filteredTasks.value.slice((taskPage.value - 1) * taskPageSize.value, taskPage.value * taskPageSize.value))
const historyOptions = computed(() => [{ title: '全部结果', value: 'all' }, ...[...new Set((status.value.history || []).map(historyOutcome))].map(value => ({ title: value, value }))])
const filteredHistory = computed(() => (status.value.history || []).filter(row => {
  const query = historySearch.value.trim().toLocaleLowerCase()
  return (!query || [row.title, row.rule_name, row.reason, row.rule_summary, row.actual_summary].filter(Boolean).join(' ').toLocaleLowerCase().includes(query))
    && (historyFilter.value === 'all' || historyOutcome(row) === historyFilter.value)
}))
const historyPageCount = computed(() => Math.max(1, Math.ceil(filteredHistory.value.length / historyPageSize.value)))
const pagedHistory = computed(() => filteredHistory.value.slice((historyPage.value - 1) * historyPageSize.value, historyPage.value * historyPageSize.value))
const taskHeaders = [
  { title: '任务', key: 'name', sortable: false, width: '34%' },
  { title: '进度', key: 'progress', sortable: false, width: 140 },
  { title: '状态', key: 'state', sortable: false, width: 120 },
  { title: '分享率', key: 'ratio', sortable: false, width: 110 },
  { title: '速度', key: 'speed', sortable: false, width: 140 },
  { title: '免费截止', key: 'free_until', sortable: false, width: 180 },
]

function notify(text, kind = 'success') {
  message.value = text
  messageKind.value = kind
  messageOpen.value = true
  if (typeof hostToast?.[kind] === 'function') hostToast[kind](text)
  if (kind === 'error') error.value = text
}

function replaceDraft(value) {
  replacingDraft = true
  draft.value = clone(value)
  draftRevision.value += 1
  replacingDraft = false
}

function ensureSelectedSite() {
  if (!sites.value.some(site => site.id === selectedSiteId.value)) selectedSiteId.value = sites.value[0]?.id || ''
  if (!selectedSite.value) activeTab.value = 'settings'
}

function historyOutcome(row) {
  return row.outcome || (row.event === 'deleted' ? '删除' : row.event === 'added' ? '下载' : '处理')
}

function siteColor(index) {
  return ['#6d4aff', '#00897b', '#d96c00', '#0277bd', '#c62828', '#6d4c41'][index % 6]
}

async function loadStatus(_preserveDraft = true, refreshTasks = true) {
  const scope = selectedSiteId.value
  const ticket = statusGate.begin(scope)
  const revision = draftRevision.value
  const epoch = configEpoch
  const wasDirty = dirty.value
  const wasSaving = saving.value
  const includeDownloaders = activeTab.value === 'settings'
  loading.value = true
  let accepted = false
  try {
    const query = new URLSearchParams({ include_tasks: 'false', include_downloaders: String(includeDownloaders) })
    if (scope) query.set('site_id', scope)
    const next = unwrap(await props.api.get(`${pluginBase}/status?${query}`))
    if (disposed || !statusGate.current(ticket, selectedSiteId.value)) return false
    if (!next?.settings || !Array.isArray(next.settings.sites)) throw new Error('配置响应不完整，已禁止保存，请重试加载')
    const previousJobs = jobs.value
    status.value = {
      ...status.value, ...next,
      history: scope && savedSettings.value.sites?.some(site => site.id === scope) ? (next.history || []).filter(row => !row.site_id || row.site_id === scope) : [],
      tasks: status.value.tasks || [],
      downloader_error: status.value.downloader_error,
      downloaders: includeDownloaders ? (next.downloaders || []) : status.value.downloaders,
    }
    if (epoch === configEpoch && !wasSaving && !saving.value) {
      savedSettings.value = clone(next.settings)
      if (!settingsLoaded.value || (!wasDirty && revision === draftRevision.value)) replaceDraft(next.settings)
      settingsLoaded.value = true
    }
    statusError.value = ''
    lastSynced.value = new Date().toISOString()
    pollFailures = 0
    const result = reconcileJobs(pendingJobs.value, jobs.value, Date.now())
    pendingJobs.value = result.pending
    for (const operation of result.finished) notify(`${operationNames[operation]}已结束，请查看处理记录确认结果`)
    for (const operation of result.unconfirmed) notify(`${operationNames[operation]}已提交，但未观测到运行记录；可能已快速结束或仍在排队，请查看记录确认`, 'warning')
    if (result.finished.length || result.unconfirmed.length || Object.keys(previousJobs).some(operation => !jobs.value[operation])) {
      if (activeTab.value === 'tasks') loadTasks(true)
    }
    accepted = true
    ensureSelectedSite()
  } catch (err) {
    if (!disposed && statusGate.current(ticket, selectedSiteId.value)) {
      statusError.value = err?.message || '加载刷流追新失败'
      pollFailures += 1
    }
  } finally {
    if (!disposed && statusGate.current(ticket, selectedSiteId.value)) {
      loading.value = false
      syncPolling()
    }
  }
  if (accepted && refreshTasks && activeTab.value === 'tasks' && scope === selectedSiteId.value) loadTasks()
  return accepted
}

async function loadTasks(force = false) {
  const siteId = selectedSiteId.value
  if (!siteId || !savedSite.value) {
    status.value.tasks = []
    return
  }
  const ticket = tasksGate.begin(siteId)
  tasksLoading.value = true
  try {
    const query = new URLSearchParams({ site_id: siteId, force: String(force) })
    const data = unwrap(await props.api.get(`${pluginBase}/tasks?${query}`))
    if (disposed || !tasksGate.current(ticket, selectedSiteId.value)) return
    status.value = { ...status.value, tasks: data.tasks || [], sites: data.sites || status.value.sites, downloader_error: data.downloader_error || null }
    lastTaskPoll = Date.now()
  } catch (err) {
    if (!disposed && tasksGate.current(ticket, selectedSiteId.value)) status.value.downloader_error = err?.message || '读取 qBittorrent 任务失败'
  } finally {
    if (!disposed && tasksGate.current(ticket, selectedSiteId.value)) tasksLoading.value = false
  }
}

function refreshPage() {
  pollDeadline = 0
  pollWarning.value = ''
  loadStatus(true, false)
  if (activeTab.value === 'tasks') loadTasks(true)
}

function selectSite(siteId) {
  selectedSiteId.value = siteId || ''
}

function addSite() {
  if (!settingsLoaded.value) return
  const id = uid()
  sites.value.push({
    id,
    name: `站点 ${sites.value.length + 1}`,
    enabled: true,
    use_proxy: false,
    user_agent: '',
    uid: '',
    passkey: '',
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
    id: uid(), name: `RSS 任务 ${selectedSite.value.rss_rules.length + 1}`, enabled: true, url: '',
    uid: '', passkey: '', rss_key: '', rss_key_name: 'rsskey', cookie: '', user_agent: '', referer: '', use_proxy: null,
    whitelist_keywords: [], blacklist_keywords: [], resolutions: [], promotion: 'any',
    publish_age_from_value: null, publish_age_from_unit: 'minutes',
    publish_age_to_value: null, publish_age_to_unit: 'minutes',
    size_from_value: null, size_from_unit: 'gib',
    size_to_value: null, size_to_unit: 'gib',
  })
}

function openAuthPage(rule) {
  authRuleId.value = rule.id
}

function addCleanupRule() {
  selectedSite.value.cleanup_rules.push({
    id: uid(), name: `删种规则 ${selectedSite.value.cleanup_rules.length + 1}`, enabled: taskNameOptions.value.length > 0,
    labels: [...taskNameOptions.value], min_seed_hours: 0, min_ratio: 0, delete_files: false,
  })
}

function updateTaskName(task, value) {
  const previous = task.name
  task.name = value
  selectedSite.value.cleanup_rules.forEach(rule => {
    rule.labels = (rule.labels || []).map(label => label === previous ? value : label)
  })
}

function removeRssRule(index) {
  const affected = removeRssAndDisableReferences(selectedSite.value, index)
  if (affected.length) referenceWarning.value = `已自动停用关联删种规则：${affected.join('、')}。请重新选择适用任务，确认后再启用。`
}

function updateCleanupLabels(rule, labels) {
  rule.labels = labels || []
  if (!rule.labels.length) rule.enabled = false
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
  if (!canSave.value) return
  const problem = validateSettings(draft.value)
  if (problem) {
    if (problem.siteId) selectedSiteId.value = problem.siteId
    activeTab.value = problem.tab || 'settings'
    notify(problem.message, 'error')
    await nextTick()
    await settingsForm.value?.validate()
    return
  }
  const payload = prepareSettings(draft.value)
  const sentRevision = draftRevision.value
  saving.value = true
  error.value = ''
  configEpoch += 1
  statusGate.invalidate()
  loading.value = false
  try {
    const data = unwrap(await props.api.post(`${pluginBase}/settings`, payload))
    if (disposed) return
    const resolved = saveResolution(draft.value, draftRevision.value, sentRevision, data?.settings, payload)
    savedSettings.value = resolved.saved
    status.value.settings = clone(resolved.saved)
    status.value.config_pending = Boolean(data?.config_pending)
    if (draftRevision.value === sentRevision) replaceDraft(resolved.draft)
    settingsLoaded.value = true
    statusError.value = ''
    ensureSelectedSite()
    notify(dirty.value ? '提交的版本已保存；保存期间的新修改仍留在草稿，请再次保存' : data?.config_pending ? '配置已保存，当前后台任务结束后自动生效' : '配置已保存，定时任务已更新')
    // Some hosts reload/close their plugin modal on action. Do not let that
    // discard edits made after this save request was sent.
    if (!dirty.value) emit('action')
  } catch (err) {
    if (disposed) return
    const details = err?.response?.data?.detail || err?.detail
    const detailText = Array.isArray(details) ? details.map(item => `${(item.loc || []).join('.')}：${item.msg || '字段无效'}`).join('；') : ''
    notify(detailText || err?.message || '保存配置失败，草稿已保留', 'error')
  } finally {
    if (!disposed) {
      configEpoch += 1
      saving.value = false
      // The save response is global (its history may be for the first site).
      // Never merge it into this site's views; re-fetch using the current scope.
      loadStatus(true, false)
    }
  }
}

function operationBusy(operation) {
  return Boolean(runSubmitting.value[operation] || pendingJobs.value[operation] || jobs.value[operation])
}

function requestCleanup() {
  if (runDisabledReason.value || operationBusy('cleanup')) return
  cleanupTarget.value = {
    siteId: savedSite.value.id, name: savedSite.value.name,
    deleteFiles: (savedSite.value.cleanup_rules || []).some(rule => rule.enabled && rule.labels?.length && rule.delete_files),
    revision: fingerprint(savedSettings.value),
  }
  cleanupDialog.value = true
}

async function confirmCleanup() {
  const target = cleanupTarget.value
  cleanupDialog.value = false
  if (!target || target.siteId !== selectedSiteId.value || target.revision !== fingerprint(savedSettings.value) || runDisabledReason.value) {
    notify('站点或配置已变化，请重新确认执行删种', 'warning')
    return
  }
  await runOperation('cleanup')
}

async function runOperation(operation) {
  if (runDisabledReason.value) { notify(runDisabledReason.value, 'warning'); return }
  if (operationBusy(operation)) return
  const siteId = savedSite.value.id
  runSubmitting.value = { ...runSubmitting.value, [operation]: true }
  try {
    unwrap(await props.api.post(`${pluginBase}/run`, { operation, site_id: siteId }))
    if (disposed) return
    pendingJobs.value = { ...pendingJobs.value, [operation]: { site_id: siteId, submitted_at: Date.now(), observed: false } }
    pollDeadline = 0
    pollWarning.value = ''
    notify(`${operationNames[operation]}已使用已保存配置提交到后台`)
    await loadStatus(true, false)
  } catch (err) {
    if (!disposed) notify(err?.message || '提交任务失败', 'error')
  } finally {
    if (!disposed) {
      runSubmitting.value = { ...runSubmitting.value, [operation]: false }
      syncPolling()
    }
  }
}

function stopPolling() {
  if (pollTimer !== null) globalThis.clearTimeout(pollTimer)
  pollTimer = null
}

function syncPolling() {
  const hasJobs = jobRows.value.length > 0
  if (disposed || !mounted || globalThis.document?.hidden || !hasJobs) {
    stopPolling()
    if (!hasJobs) { pollDeadline = 0; pollWarning.value = '' }
    return
  }
  if (!pollDeadline) pollDeadline = Date.now() + POLL_BUDGET
  if (Date.now() >= pollDeadline) {
    stopPolling()
    pollWarning.value = '自动追踪已达到 15 分钟预算，后台任务不会被取消。点击刷新可继续追踪。'
    return
  }
  if (pollTimer !== null) return
  pollTimer = globalThis.setTimeout(async () => {
    pollTimer = null
    if (disposed || globalThis.document?.hidden) return
    await loadStatus(true, false)
    if (!disposed && !globalThis.document?.hidden && activeTab.value === 'tasks' && !tasksLoading.value && Date.now() - lastTaskPoll >= 8000) loadTasks(true)
    syncPolling()
  }, Math.min(10000, 2000 * (1 + pollFailures)))
}

async function testDownloader() {
  if (testing.value || !settingsLoaded.value) return
  testing.value = true
  try {
    const data = unwrap(await props.api.post(`${pluginBase}/test-downloader`, {
      downloader: draft.value.downloader || '',
      downloader_mode: draft.value.downloader_mode || 'moviepilot',
      custom_qb_url: draft.value.custom_qb_url || '',
      custom_qb_host: draft.value.custom_qb_host || '',
      custom_qb_port: Number(draft.value.custom_qb_port || 8080),
      custom_qb_username: draft.value.custom_qb_username || '',
      custom_qb_password: draft.value.custom_qb_password || '',
      custom_qb_save_path: draft.value.custom_qb_save_path || '',
    }))
    if (!disposed) notify(`连接正常，当前 ${data.torrent_count} 个任务（测试使用当前草稿，不会保存）`)
  } catch (err) {
    if (!disposed) notify(err?.message || 'qBittorrent 连接失败', 'error')
  } finally {
    if (!disposed) testing.value = false
  }
}

function historyMeta(row) {
  const parts = [row.outcome || (row.event === 'added' ? '下载' : row.event === 'deleted' ? '删除' : '处理')]
  if (row.reason) parts.push(row.reason)
  else parts.push(row.rule_name || 'RSS 任务', row.resolution || '未知画质')
  if (Number(row.size || 0) > 0) parts.push(formatBytes(row.size))
  return parts.join(' · ')
}

function historyIcon(row) {
  if (row.event === 'deleted') return 'mdi-delete-circle-outline'
  if (row.outcome === '排除') return 'mdi-close-circle-outline'
  if (row.outcome === '失败') return 'mdi-alert-circle-outline'
  return 'mdi-download-circle-outline'
}

function historyColor(row) {
  if (row.outcome === '排除') return 'error'
  if (row.event === 'deleted' || row.outcome === '失败') return 'warning'
  return 'success'
}

function discardChanges() {
  replaceDraft(savedSettings.value)
  discardDialog.value = false
  referenceWarning.value = ''
  ensureSelectedSite()
}
function requestClose() {
  if (dirty.value || saving.value) leaveDialog.value = true
  else emit('close')
}
function beforeUnload(event) {
  if (!dirty.value && !saving.value) return
  event.preventDefault()
  event.returnValue = ''
}
function visibilityChanged() {
  if (clockTimer !== null) globalThis.clearInterval(clockTimer)
  clockTimer = null
  if (globalThis.document?.hidden) { stopPolling(); return }
  now.value = Date.now()
  clockTimer = globalThis.setInterval(() => { now.value = Date.now() }, 30000)
  if (mounted) { pollDeadline = 0; loadStatus(true, false) }
}

watch(draft, () => { if (!replacingDraft) draftRevision.value += 1 }, { deep: true, flush: 'sync' })
watch(() => props.initialTab, value => { if (value) activeTab.value = value })
watch(selectedSiteId, () => {
  statusGate.invalidate()
  tasksGate.invalidate()
  loading.value = false
  tasksLoading.value = false
  status.value = { ...status.value, tasks: [], history: [], downloader_error: null }
  authRuleId.value = null
  cleanupDialog.value = false
  deleteSiteDialog.value = false
  taskPage.value = 1
  historyPage.value = 1
  taskRuleFilter.value = null
  historyFilter.value = 'all'
  if (mounted) loadStatus(true)
}, { flush: 'sync' })
watch(activeTab, value => {
  if (!mounted) return
  if (value === 'tasks') loadTasks()
  if (value === 'settings') loadStatus(true, false)
})
watch([taskSearch, taskStateFilter, taskRuleFilter, taskPageSize], () => { taskPage.value = 1 })
watch([historySearch, historyFilter, historyPageSize], () => { historyPage.value = 1 })
watch(taskPageCount, count => { taskPage.value = Math.min(taskPage.value, count) })
watch(historyPageCount, count => { historyPage.value = Math.min(historyPage.value, count) })
onMounted(() => {
  mounted = true
  globalThis.addEventListener?.('beforeunload', beforeUnload)
  globalThis.document?.addEventListener('visibilitychange', visibilityChanged)
  visibilityChanged()
  // Embedded/hidden WebViews still need their initial configuration; only
  // periodic polling waits for visibility.
  if (globalThis.document?.hidden) loadStatus(true)
})
onBeforeUnmount(() => {
  disposed = true
  mounted = false
  stopPolling()
  if (clockTimer !== null) globalThis.clearInterval(clockTimer)
  statusGate.invalidate()
  tasksGate.invalidate()
  globalThis.removeEventListener?.('beforeunload', beforeUnload)
  globalThis.document?.removeEventListener('visibilitychange', visibilityChanged)
})
</script>

<template>
  <VForm ref="settingsForm" class="tracker" :disabled="!settingsLoaded" :class="{ 'tracker--compact': compact }" @submit.prevent="saveSettings">
    <header class="tracker__header">
      <div class="tracker__identity">
        <VIcon icon="mdi-rss-box" color="primary" size="30" />
        <div><h1>刷流追新</h1><p>一个 qBittorrent，统一托管多站点任务</p></div>
      </div>
      <div class="tracker__actions">
        <VTooltip text="刷新数据"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-refresh" variant="text" :loading="loading || tasksLoading" @click="refreshPage" /></template></VTooltip>
        <VBtn variant="text" class="global-settings-button" aria-label="全局设置" @click="activeTab = 'settings'"><VIcon icon="mdi-tune-variant" /><span class="global-settings-label">全局设置</span></VBtn>
        <VBtn color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" :disabled="!canSave" @click="saveSettings">保存</VBtn>
        <VTooltip v-if="showClose" text="关闭"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-close" variant="text" @click="requestClose" /></template></VTooltip>
      </div>
    </header>

    <VAlert v-if="statusError" type="error" variant="tonal">{{ statusError }}。保存与手动运行已禁用。<VBtn size="small" variant="text" :loading="loading" @click="refreshPage">重试加载</VBtn></VAlert>
    <VAlert v-if="error" type="error" variant="tonal" closable @click:close="error = ''">{{ error }}</VAlert>
    <VAlert v-if="status.downloader_error" type="warning" variant="tonal">下载器读取失败：{{ status.downloader_error }}<span v-if="status.tasks.length">（以下保留最近一次快照）</span></VAlert>
    <VAlert v-if="status.config_pending" type="info" variant="tonal">新配置已保存，当前后台任务仍使用原配置；本轮结束后自动应用。</VAlert>
    <VAlert v-if="status.state_save_pending" type="warning" variant="tonal">运行状态尚未完成落盘，后台补写及后续任务会继续重试。</VAlert>
    <VAlert v-if="referenceWarning" type="warning" variant="tonal" closable @click:close="referenceWarning = ''">{{ referenceWarning }}</VAlert>
    <VAlert v-if="pollWarning" type="warning" variant="tonal">{{ pollWarning }}<VBtn variant="text" @click="refreshPage">继续追踪</VBtn></VAlert>
    <div v-if="jobRows.length" class="job-status" role="status" aria-live="polite">
      <div v-for="job in jobRows" :key="job.operation"><VProgressCircular indeterminate size="16" width="2" /><span>{{ job.name }} · {{ job.siteName }} · {{ job.pending ? '已提交，等待后台状态' : `运行中 ${job.running_seconds || 0} 秒` }}</span></div>
    </div>
    <div class="sync-note">{{ dirty ? '有未保存修改' : settingsLoaded ? '当前配置已保存' : '等待加载配置' }} · 最近同步 {{ formatTime(lastSynced) }}</div>

    <div v-if="loading && !settingsLoaded" class="tracker__loading"><VSkeletonLoader type="list-item-three-line, article" /></div>
    <div v-else class="tracker__layout">
      <VSheet tag="aside" class="site-rail app-surface-static">
        <div class="site-rail__head"><strong>站点</strong></div>
        <div class="site-list">
          <button v-for="(site, index) in sites" :key="site.id" type="button" class="site-item" :class="{ 'site-item--active': site.id === selectedSiteId }" :style="{ '--site-color': siteColor(index) }" @click="selectSite(site.id)">
            <span><i :class="{ online: site.enabled }" />{{ site.name || '未命名站点' }}</span>
            <small>{{ site.rss_rules.length }} 条 RSS · {{ site.cleanup_rules.length }} 条删种</small>
          </button>
          <button type="button" class="site-item site-add" :disabled="!settingsLoaded" style="--site-color: #6d4aff" @click="addSite">
            <span><VIcon icon="mdi-plus" size="18" />新增站点</span>
            <small>创建新的站点配置</small>
          </button>
        </div>
      </VSheet>

      <main class="workspace">
        <div class="mobile-site"><VSelect :model-value="selectedSiteId" :items="sites" item-title="name" item-value="id" label="当前站点" placeholder="尚未添加站点" hide-details @update:model-value="selectSite" /><VBtn color="primary" variant="tonal" prepend-icon="mdi-plus" :disabled="!settingsLoaded" @click="addSite">新增</VBtn></div>

        <div v-if="selectedSite" class="site-head">
            <div class="site-head__name">
              <VTextField v-model="selectedSite.name" label="站点名称" variant="outlined" density="compact" :rules="[value => Boolean(String(value || '').trim()) || '站点名称不能为空']" hide-details="auto" />
              <VChip :color="selectedSite.enabled ? 'success' : 'default'" size="small" variant="tonal">{{ selectedSite.enabled ? '启用' : '停用' }}</VChip>
            </div>
            <div class="site-head__actions">
              <VSwitch v-model="selectedSite.enabled" label="启用站点" hide-details color="success" inset />
              <VTooltip text="删除站点"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-delete-outline" color="error" variant="text" @click="deleteSiteDialog = true" /></template></VTooltip>
            </div>
          </div>

          <VTabs v-model="activeTab" class="tracker-tabs" show-arrows>
            <VTab value="tasks" prepend-icon="mdi-download-network-outline" :disabled="!selectedSite">任务</VTab>
            <VTab value="rss" prepend-icon="mdi-rss" :disabled="!selectedSite">RSS 任务</VTab>
            <VTab value="cleanup" prepend-icon="mdi-broom" :disabled="!selectedSite">删种规则</VTab>
            <VTab value="history" prepend-icon="mdi-history" :disabled="!selectedSite">记录</VTab>
            <VTab value="site" prepend-icon="mdi-shield-key-outline" :disabled="!selectedSite">站点认证</VTab>
            <VTab value="settings" prepend-icon="mdi-tune-variant">全局设置</VTab>
          </VTabs>

          <VWindow v-model="activeTab" class="tracker-window">
            <VWindowItem v-if="selectedSite" value="tasks">
              <div class="stats">
                <VSheet class="stat app-surface-static"><span>托管任务</span><strong>{{ selectedSummary.managed_count || 0 }}</strong><VIcon icon="mdi-download-circle-outline" color="primary" /></VSheet>
                <VSheet class="stat app-surface-static"><span>RSS 任务</span><strong>{{ selectedSite.rss_rules.length }}</strong><VIcon icon="mdi-rss" color="info" /></VSheet>
                <VSheet class="stat app-surface-static"><span>最近读取</span><strong>{{ selectedSummary.stats?.fetched || 0 }}</strong><VIcon icon="mdi-text-box-search-outline" color="warning" /></VSheet>
                <VSheet class="stat app-surface-static"><span>最近添加</span><strong>{{ selectedSummary.stats?.added || 0 }}</strong><VIcon icon="mdi-check-circle-outline" color="success" /></VSheet>
              </div>
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>本插件托管的 qBittorrent 任务</h2><p>{{ downloaderLabel }}</p></div><div class="operation-actions"><VBtn variant="tonal" prepend-icon="mdi-rss" :loading="operationBusy('rss')" :disabled="Boolean(runDisabledReason) || operationBusy('rss')" @click="runOperation('rss')">立即刷新 RSS</VBtn><VBtn color="error" variant="text" prepend-icon="mdi-broom" :loading="operationBusy('cleanup')" :disabled="Boolean(runDisabledReason) || operationBusy('cleanup')" @click="requestCleanup">执行删种</VBtn></div></header>
                <p class="operation-hint">{{ runDisabledReason || '手动运行使用服务器已保存配置；执行删种可能删除任务及文件。' }}</p>
                <div class="list-filters">
                  <VTextField v-model="taskSearch" label="搜索任务名称 / 标签" prepend-inner-icon="mdi-magnify" clearable hide-details @update:model-value="taskSearch = $event || ''" />
                  <VSelect v-model="taskStateFilter" :items="stateOptions" label="状态" hide-details />
                  <VSelect v-model="taskRuleFilter" :items="taskFilterOptions" label="任务标签" clearable hide-details />
                </div>
                <VProgressLinear v-if="tasksLoading" indeterminate color="primary" aria-label="正在加载当前站点任务" />
                <div v-if="!filteredTasks.length" class="empty-table">
                  {{ tasksLoading ? '正在读取当前站点任务…' : status.downloader_error ? '下载器离线或读取失败，请重试' : !savedSite ? '新站点尚未保存，保存后可读取托管任务' : (status.tasks || []).length ? '没有符合搜索 / 筛选条件的任务' : '当前站点没有托管任务' }}
                </div>
                <template v-else>
                  <div class="task-table-wrap">
                    <VDataTable :headers="taskHeaders" :items="pagedTasks" :items-per-page="-1" :mobile="false" hide-default-footer density="comfortable" class="task-table">
                      <template #item.name="{ item }"><div class="task-name"><TaskTitle :name="item.name" /><small>{{ formatBytes(item.size) }} · {{ taskTags(item).join(' · ') || '无标签' }}</small><small v-if="pauseExplanation(item)">{{ pauseExplanation(item) }}</small></div></template>
                      <template #item.progress="{ item }"><div class="progress-cell"><span>{{ taskProgress(item).toFixed(1) }}%</span><VProgressLinear :model-value="taskProgress(item)" height="6" rounded color="primary" /></div></template>
                      <template #item.state="{ item }"><VChip :color="taskState(item).color" size="small" variant="tonal">{{ taskState(item).title }}</VChip></template>
                      <template #item.ratio="{ item }">{{ Number(item.ratio || 0).toFixed(2) }}<small class="block-muted">做种 {{ formatDuration(item.seeding_time) }}</small></template>
                      <template #item.speed="{ item }"><span>↓ {{ formatBytes(item.dlspeed) }}/s</span><small class="block-muted">↑ {{ formatBytes(item.upspeed) }}/s</small></template>
                      <template #item.free_until="{ item }"><span :class="{ 'text-warning': freeRemaining(item.free_until, now).urgent }">{{ freeRemaining(item.free_until, now).text }}</span><small v-if="item.free_until" class="block-muted">{{ formatTime(item.free_until) }}</small></template>
                    </VDataTable>
                  </div>
                  <div class="task-cards">
                    <article v-for="item in pagedTasks" :key="item.hash || item.name" class="task-card">
                      <TaskTitle :name="item.name" />
                      <div class="task-card__meta"><VChip :color="taskState(item).color" size="small" variant="tonal">{{ taskState(item).title }}</VChip><span>{{ formatBytes(item.size) }}</span><span>{{ taskTags(item).join(' · ') || '无标签' }}</span></div>
                      <div class="task-card__progress"><div><span>下载进度</span><strong>{{ taskProgress(item).toFixed(1) }}%</strong></div><VProgressLinear :model-value="taskProgress(item)" height="7" rounded color="primary" /></div>
                      <div class="task-card__metrics"><span>↓ {{ formatBytes(item.dlspeed) }}/s</span><span>↑ {{ formatBytes(item.upspeed) }}/s</span><span>分享率 {{ Number(item.ratio || 0).toFixed(2) }}</span><span>做种 {{ formatDuration(item.seeding_time) }}</span></div>
                      <div class="task-card__deadline" :class="{ 'text-warning': freeRemaining(item.free_until, now).urgent }">{{ freeRemaining(item.free_until, now).text }}<small v-if="item.free_until" class="block-muted">截止 {{ formatTime(item.free_until) }}</small></div>
                      <p v-if="pauseExplanation(item)" class="task-card__reason">{{ pauseExplanation(item) }}</p>
                    </article>
                  </div>
                </template>
                <div class="list-pagination"><span>共 {{ filteredTasks.length }} 个任务</span><VSelect v-model="taskPageSize" :items="[10, 20, 50]" label="每页" hide-details density="compact" /><VPagination v-model="taskPage" :length="taskPageCount" :total-visible="3" density="comfortable" aria-label="任务分页" /></div>
              </VSheet>
            </VWindowItem>

            <VWindowItem v-if="selectedSite" value="rss">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>RSS 选种任务</h2><p>任务名会自动作为 qBittorrent 标签；未选择分辨率时参与最高画质去重</p></div><VBtn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="addRssRule">新增任务</VBtn></header>
                <div v-if="!selectedSite.rss_rules.length" class="empty-state"><VIcon icon="mdi-rss-off" size="46" /><strong>尚未配置 RSS 任务</strong><VBtn variant="tonal" @click="addRssRule">新增任务</VBtn></div>
                <VExpansionPanels v-else multiple variant="accordion" class="rule-list">
                  <VExpansionPanel v-for="(rule, index) in selectedSite.rss_rules" :key="rule.id">
                    <VExpansionPanelTitle><div class="rule-title"><VIcon icon="mdi-rss" color="info" /><div class="rule-title__text"><strong>{{ rule.name || `RSS 任务 ${index + 1}` }}</strong><small>{{ ruleSummary(rule) }}</small></div><VChip size="x-small" :color="rule.enabled ? 'success' : 'default'" variant="tonal">{{ rule.enabled ? '启用' : '停用' }}</VChip></div></VExpansionPanelTitle>
                    <VExpansionPanelText>
                      <div class="rule-grid">
                        <VTextField :model-value="rule.name" label="任务名称（同时作为标签）" :rules="[value => Boolean(String(value || '').trim()) || '任务名称不能为空', value => !String(value || '').includes(',') || '不能包含英文逗号']" hide-details="auto" @update:model-value="updateTaskName(rule, $event)" />
                        <VSwitch v-model="rule.enabled" label="启用规则" hide-details color="success" inset />
                        <VTextField v-model="rule.url" class="span-2" label="RSS 订阅地址" placeholder="https://tracker.example/torrentrss.php?..." hide-details />
                        <VCombobox v-model="rule.whitelist_keywords" label="白名单关键词（必须全部包含）" multiple chips closable-chips hide-details />
                        <VCombobox v-model="rule.blacklist_keywords" label="黑名单关键词（命中任一个即排除）" multiple chips closable-chips hide-details />
                        <VSelect v-model="rule.resolutions" :items="resolutionOptions" label="分辨率筛选" multiple chips closable-chips clearable hide-details />
                        <VSelect v-model="rule.promotion" :items="promotionOptions" label="免费期筛选" hide-details />
                        <div class="range-control">
                          <span>发种时间范围</span>
                          <div class="range-fields range-fields--units"><div class="value-unit"><VTextField v-model.number="rule.publish_age_from_value" type="number" min="0" label="从" clearable hide-details /><VSelect v-model="rule.publish_age_from_unit" :items="timeUnitOptions" aria-label="起始时间单位" hide-details /></div><b>至</b><div class="value-unit"><VTextField v-model.number="rule.publish_age_to_value" type="number" min="0" label="到" clearable hide-details /><VSelect v-model="rule.publish_age_to_unit" :items="timeUnitOptions" aria-label="结束时间单位" hide-details /></div></div>
                        </div>
                        <div class="range-control">
                          <span>种子大小范围</span>
                          <div class="range-fields range-fields--units"><div class="value-unit"><VTextField v-model.number="rule.size_from_value" type="number" min="0" step="0.1" label="从" clearable hide-details /><VSelect v-model="rule.size_from_unit" :items="sizeUnitOptions" aria-label="起始体积单位" hide-details /></div><b>至</b><div class="value-unit"><VTextField v-model.number="rule.size_to_value" type="number" min="0" step="0.1" label="到" clearable hide-details /><VSelect v-model="rule.size_to_unit" :items="sizeUnitOptions" aria-label="结束体积单位" hide-details /></div></div>
                        </div>
                      </div>
                      <div class="rule-actions"><VTooltip text="上移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-up" size="small" variant="text" :disabled="index === 0" @click="moveRule(selectedSite.rss_rules, index, -1)" /></template></VTooltip><VTooltip text="下移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-down" size="small" variant="text" :disabled="index === selectedSite.rss_rules.length - 1" @click="moveRule(selectedSite.rss_rules, index, 1)" /></template></VTooltip><VSpacer /><VBtn variant="tonal" color="primary" prepend-icon="mdi-shield-key-outline" @click="openAuthPage(rule)">认证/防403</VBtn><VBtn color="error" variant="text" prepend-icon="mdi-delete-outline" @click="removeRssRule(index)">删除</VBtn></div>
                    </VExpansionPanelText>
                  </VExpansionPanel>
                </VExpansionPanels>
              </VSheet>
            </VWindowItem>

            <VWindowItem v-if="selectedSite" value="cleanup">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>顺序删种规则</h2><p>每个任务只执行第一条标签与阈值均命中的规则</p></div><VBtn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="addCleanupRule">新增规则</VBtn></header>
                <div v-if="!selectedSite.cleanup_rules.length" class="empty-state"><VIcon icon="mdi-broom" size="46" /><strong>尚未配置自动删种</strong><VBtn variant="tonal" @click="addCleanupRule">新增规则</VBtn></div>
                <div v-else class="cleanup-list">
                  <VSheet v-for="(rule, index) in selectedSite.cleanup_rules" :key="rule.id" class="cleanup-rule">
                    <div class="order">{{ index + 1 }}</div>
                    <div class="cleanup-fields">
                      <p class="cleanup-summary">{{ rule.enabled ? '启用' : '停用' }} · {{ rule.labels?.join(' / ') || '未选择任务（不执行）' }} · 做种 ≥ {{ rule.min_seed_hours || 0 }} 小时且分享率 ≥ {{ rule.min_ratio || 0 }} · {{ rule.delete_files ? '同时删除文件' : '保留文件' }}</p>
                      <VAlert v-if="!rule.labels?.length" class="span-2" type="warning" variant="tonal" density="compact">未选择适用任务，规则不会执行。请重新关联后启用。</VAlert>
                      <VTextField v-model="rule.name" label="规则名称" hide-details />
                      <VSelect :model-value="rule.labels" :items="taskNameOptions" label="适用任务标签（任一匹配）" multiple chips closable-chips hide-details @update:model-value="updateCleanupLabels(rule, $event)" />
                      <VTextField v-model.number="rule.min_seed_hours" type="number" min="0" step="0.5" label="满足做种小时数" suffix="小时" hide-details />
                      <VTextField v-model.number="rule.min_ratio" type="number" min="0" step="0.1" label="满足分享率" hide-details />
                      <VSwitch v-model="rule.enabled" label="启用" :disabled="!rule.labels?.length" hide-details color="success" inset />
                      <VSwitch v-model="rule.delete_files" label="同时删除文件" hide-details color="error" inset />
                    </div>
                    <div class="vertical-actions"><VTooltip text="上移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-up" size="small" variant="text" :disabled="index === 0" @click="moveRule(selectedSite.cleanup_rules, index, -1)" /></template></VTooltip><VTooltip text="下移"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-arrow-down" size="small" variant="text" :disabled="index === selectedSite.cleanup_rules.length - 1" @click="moveRule(selectedSite.cleanup_rules, index, 1)" /></template></VTooltip><VTooltip text="删除"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-delete-outline" size="small" color="error" variant="text" @click="removeRule(selectedSite.cleanup_rules, index)" /></template></VTooltip></div>
                  </VSheet>
                </div>
              </VSheet>
            </VWindowItem>

            <VWindowItem v-if="selectedSite" value="history">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>处理记录</h2><p>对比规则条件与实际检测结果；点击名称进入种子页面</p></div></header>
                <div class="list-filters history-filters"><VTextField v-model="historySearch" label="搜索标题 / 任务名称 / 原因" prepend-inner-icon="mdi-magnify" clearable hide-details @update:model-value="historySearch = $event || ''" /><VSelect v-model="historyFilter" :items="historyOptions" label="处理结果" hide-details /></div>
                <VProgressLinear v-if="loading" indeterminate color="primary" aria-label="正在加载当前站点记录" />
                <div class="history-list"><article v-for="(row, index) in pagedHistory" :key="`${row.time}-${row.title}-${row.outcome}-${index}`"><VIcon :icon="historyIcon(row)" :color="historyColor(row)" /><div><a v-if="row.link" :href="row.link" target="_blank" rel="noopener noreferrer">{{ row.title }}</a><strong v-else>{{ row.title }}</strong><span class="history-result">{{ historyMeta(row) }}</span><span v-if="row.rule_summary"><b>规则条件：</b>{{ row.rule_summary }}</span><span v-if="row.actual_summary"><b>实际检测：</b>{{ row.actual_summary }}</span></div><time>{{ formatTime(row.time) }}</time></article><div v-if="!filteredHistory.length" class="empty-table">{{ loading ? '正在读取当前站点记录…' : statusError ? '记录加载失败，请重试' : status.history?.length ? '没有符合搜索 / 筛选条件的记录' : '暂无处理记录' }}</div></div>
                <div class="list-pagination"><span>已加载 {{ status.history?.length || 0 }} 条 · 符合 {{ filteredHistory.length }} 条</span><VSelect v-model="historyPageSize" :items="[10, 20, 50]" label="每页" hide-details density="compact" /><VPagination v-model="historyPage" :length="historyPageCount" :total-visible="3" density="comfortable" aria-label="记录分页" /></div>
                <p class="block-muted">分页与搜索基于 status 接口返回的最近记录，不代表全部历史。</p>
              </VSheet>
            </VWindowItem>

            <VWindowItem v-if="selectedSite" value="site">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>站点认证与默认请求设置</h2><p>仅作用于当前站点；RSS 任务可以单独覆盖这些设置</p></div></header>
                <div class="settings-grid">
                  <VSwitch v-model="selectedSite.use_proxy" label="本站点默认使用代理" hide-details inset />
                  <VTextField v-model="selectedSite.user_agent" class="span-2" label="站点自定义 User-Agent" clearable hide-details />
                  <VTextField v-model="selectedSite.uid" label="站点 UID（可选）" hint="自动补到 RSS / 详情地址" persistent-hint hide-details="auto" />
                  <VTextField v-model="selectedSite.passkey" type="password" label="站点 Passkey（可选）" hint="仅在保存后生效" persistent-hint hide-details="auto" />
                </div>
              </VSheet>
            </VWindowItem>

            <VWindowItem value="settings">
              <VSheet class="panel app-surface-static">
                <header class="panel__head"><div><h2>全局连接与调度</h2><p>所有站点共用这一项 qBittorrent 配置</p></div></header>
                <div class="settings-grid">
                  <VSwitch v-model="draft.enabled" label="启用插件" color="success" hide-details inset />
                  <VSwitch v-model="draft.show_sidebar_nav" label="显示侧栏入口" hide-details inset />
                  <VSelect v-model="draft.downloader_mode" :items="[{ title: 'MoviePilot 内置下载器', value: 'moviepilot' }, { title: '自定义 qBittorrent', value: 'custom' }]" label="qBittorrent 连接方式" hide-details />
                  <VSelect v-if="draft.downloader_mode !== 'custom'" v-model="draft.downloader" class="span-2" :items="status.downloaders" label="MoviePilot qBittorrent 下载器" placeholder="选择 MoviePilot 中已配置的 qBittorrent" hide-details><template #append><VTooltip text="测试连接"><template #activator="{ props: tip }"><VBtn v-bind="tip" icon="mdi-connection" variant="text" :loading="testing" :disabled="!settingsLoaded" @click="testDownloader" /></template></VTooltip></template></VSelect>
                  <template v-else>
                    <VTextField v-model="draft.custom_qb_url" label="qBittorrent WebUI 地址" placeholder="http://127.0.0.1:8080" hide-details />
                    <VTextField v-model="draft.custom_qb_username" label="qBittorrent 用户名" hide-details />
                    <VTextField v-model="draft.custom_qb_password" type="password" label="qBittorrent 密码" hide-details />
                    <VTextField v-model="draft.custom_qb_save_path" class="span-2" label="下载保存路径（可选）" placeholder="/downloads 或 D:\\Downloads" hide-details />
                    <VBtn class="span-2" variant="tonal" prepend-icon="mdi-connection" :loading="testing" :disabled="!settingsLoaded" @click="testDownloader">测试自定义 qBittorrent 连接</VBtn>
                  </template>
                  <VSwitch v-model="draft.highest_resolution_dedup" class="span-2" label="重复下载只保留最佳版本（已下载完成的内容不会删除）" color="primary" hide-details inset />
                  <VSwitch v-model="draft.avoid_dead_seeds" class="span-2" label="避开无做种死种并自动切换可下载版本" color="warning" hide-details inset />
                  <VTextField v-model.number="draft.dead_seed_wait_minutes" type="number" min="1" label="死种等待时间" suffix="分钟" hide-details />
                  <VTextField v-model.number="draft.dead_seed_min_seeders" type="number" min="0" label="最低做种数" suffix="个" hide-details />
                  <VSwitch v-model="draft.dead_seed_delete_files" label="死种删除文件" color="error" hide-details inset />
                  <VTextField v-model.number="draft.rss_interval_minutes" type="number" min="1" label="RSS 刷新间隔（分钟）" hide-details />
                  <VTextField v-model.number="draft.free_monitor_interval_minutes" type="number" min="1" label="免费期检查间隔（分钟）" hide-details />
                  <VTextField v-model.number="draft.cleanup_interval_minutes" type="number" min="1" label="自动删种间隔（分钟）" hide-details />
                  <VTextField v-model.number="draft.request_timeout_seconds" type="number" min="5" max="120" label="RSS 请求超时（秒）" hide-details />
                  <VTextField v-model.number="draft.history_limit" type="number" min="50" max="5000" label="历史记录上限" hide-details />
                </div>
                <p class="operation-hint">连接测试使用当前输入，不会保存；{{ runDisabledReason || '手动检查使用已保存的当前站点配置。' }}</p>
                <div class="settings-actions"><VBtn color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" :disabled="!canSave" @click="saveSettings">保存全部设置</VBtn><VBtn variant="tonal" prepend-icon="mdi-timer-refresh-outline" :loading="operationBusy('free_monitor')" :disabled="Boolean(runDisabledReason) || operationBusy('free_monitor')" @click="runOperation('free_monitor')">检查免费期</VBtn></div>
              </VSheet>
            </VWindowItem>
          </VWindow>

        <div v-if="!selectedSite && settingsLoaded" class="empty-state empty-workspace"><VIcon icon="mdi-web-off" size="56" /><strong>还没有站点</strong><p>可以先在全局设置配置下载器，再新增站点。</p><VBtn color="primary" variant="flat" prepend-icon="mdi-plus" @click="addSite">创建第一个站点</VBtn></div>
      </main>
    </div>

    <VDialog v-model="authDialog" max-width="52rem" scrollable>
      <VCard v-if="authRule" title="任务认证与防 403">
        <VCardText>
          <p class="block-muted auth-help">此页面只作用于当前 RSS 任务。任务级填写优先于站点默认值；留空则继承站点设置或 MoviePilot 站点 Cookie。</p>
          <div class="rule-grid auth-grid">
            <VTextField v-model="authRule.uid" label="UID" placeholder="站点用户 UID" hide-details />
            <VTextField v-model="authRule.passkey" label="Passkey" type="password" placeholder="站点 Passkey" hide-details />
            <VTextField v-model="authRule.rss_key" label="RSS 密钥" type="password" placeholder="站点提供的 RSS Key" hide-details />
            <VTextField v-model="authRule.rss_key_name" label="RSS 密钥参数名" placeholder="默认 rsskey，也可能是 authkey" hide-details />
            <VTextarea v-model="authRule.cookie" class="span-2" label="Cookie（可选）" placeholder="从浏览器复制的完整 Cookie，例如 c_secure_uid=...; c_secure_pass=..." rows="3" auto-grow hide-details />
            <VTextField v-model="authRule.user_agent" label="User-Agent（可选）" placeholder="留空使用站点/MoviePilot 默认值" hide-details />
            <VTextField v-model="authRule.referer" label="Referer（可选）" placeholder="https://站点域名/" hide-details />
            <VSelect :model-value="authRule.use_proxy ?? null" :items="proxyOptions" label="此任务代理策略" hint="继承站点 / 强制开启 / 强制关闭" persistent-hint hide-details="auto" @update:model-value="authRule.use_proxy = $event" />
          </div>
          <VAlert class="auth-alert" type="info" variant="tonal" density="compact">Audiences/NexusPHP 页面只显示“免费”徽章时，建议同时填写 Cookie；UID/Passkey 会自动补到 RSS 和详情地址。</VAlert>
        </VCardText>
        <VCardActions><VSpacer /><VBtn variant="text" @click="authRuleId = null">关闭</VBtn></VCardActions>
      </VCard>
    </VDialog>
    <VDialog v-model="deleteSiteDialog" max-width="28rem"><VCard title="删除站点"><VCardText>删除“{{ selectedSite?.name }}”及其所有规则？下载器中的现有任务不会被删除。此修改在保存后生效。</VCardText><VCardActions><VSpacer /><VBtn variant="text" @click="deleteSiteDialog = false">取消</VBtn><VBtn color="error" variant="flat" @click="confirmDeleteSite">删除</VBtn></VCardActions></VCard></VDialog>
    <VDialog v-model="cleanupDialog" max-width="30rem"><VCard title="确认执行删种"><VCardText><p>作用站点：<strong>{{ cleanupTarget?.name }}</strong></p><p>将使用服务器已保存的删种规则，立即删除符合条件的托管任务。这不是只读预览。</p><VAlert :type="cleanupTarget?.deleteFiles ? 'error' : 'warning'" variant="tonal">{{ cleanupTarget?.deleteFiles ? '启用规则包含「同时删除文件」，符合条件的数据文件也会被删除，无法撤销。' : '当前启用的删种规则保留文件，只从下载器移除符合条件的任务。' }}</VAlert></VCardText><VCardActions><VSpacer /><VBtn @click="cleanupDialog = false">取消</VBtn><VBtn color="error" variant="flat" :disabled="Boolean(runDisabledReason) || operationBusy('cleanup')" @click="confirmCleanup">确认执行删种</VBtn></VCardActions></VCard></VDialog>
    <VDialog v-model="discardDialog" max-width="28rem"><VCard title="放弃未保存修改？"><VCardText>所有站点的本地草稿将恢复为最近一次已保存配置。</VCardText><VCardActions><VSpacer /><VBtn @click="discardDialog = false">继续编辑</VBtn><VBtn color="warning" :disabled="saving" @click="discardChanges">放弃修改</VBtn></VCardActions></VCard></VDialog>
    <VDialog v-model="leaveDialog" max-width="28rem"><VCard title="尚有未保存修改"><VCardText>{{ saving ? '保存仍在提交中，建议等待结果后再关闭。' : '关闭会丢失未保存的草稿，确定离开？' }}</VCardText><VCardActions><VSpacer /><VBtn @click="leaveDialog = false">继续编辑</VBtn><VBtn color="warning" @click="$emit('close')">仍然关闭</VBtn></VCardActions></VCard></VDialog>
    <div v-if="dirty || saving" class="save-bar" role="status"><span>{{ saving ? '正在保存提交的版本；可以继续编辑' : '有未保存修改 · 手动运行暂不可用' }}</span><div><VBtn variant="text" :disabled="saving" @click="discardDialog = true">放弃</VBtn><VBtn color="primary" variant="flat" :loading="saving" :disabled="!canSave" @click="saveSettings">保存全部修改</VBtn></div></div>
    <VSnackbar v-model="messageOpen" :color="messageKind" :timeout="6000">{{ message }}<template #actions><VBtn variant="text" @click="messageOpen = false">关闭</VBtn></template></VSnackbar>
  </VForm>
</template>

<style scoped>
.tracker { display: flex; flex-direction: column; gap: 16px; min-inline-size: 0; padding: 16px; }
.tracker--compact { padding: 20px; }
.tracker__header, .tracker__identity, .tracker__actions, .site-rail__head, .site-head, .site-head__name, .site-head__actions, .panel__head, .operation-actions, .rule-title, .rule-actions { display: flex; align-items: center; }
.tracker__header, .site-rail__head, .site-head, .panel__head { justify-content: space-between; gap: 12px; }
.tracker__identity { gap: 12px; min-inline-size: 0; }
.tracker__identity h1, .panel h2 { margin: 0; font-size: 1.25rem; line-height: 1.35; letter-spacing: 0; }
.tracker__identity p, .panel__head p { margin: 2px 0 0; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: .85rem; }
.tracker__actions, .site-head__actions, .operation-actions, .rule-title, .rule-actions { gap: 8px; }
.tracker__loading, .empty-workspace { min-block-size: 24rem; }
.tracker__layout { display: grid; grid-template-columns: minmax(14rem, .3fr) minmax(0, 1.7fr); align-items: start; gap: 18px; }
.site-rail { position: sticky; top: 76px; display: flex; flex-direction: column; gap: 10px; max-block-size: calc(100dvh - 100px); padding: 12px; border: var(--app-surface-border); border-radius: var(--app-surface-radius); }
.site-list { display: flex; flex-direction: column; gap: 7px; min-block-size: 0; overflow-y: auto; }
.site-item { display: flex; flex: 0 0 72px; flex-direction: column; justify-content: center; gap: 5px; inline-size: 100%; min-block-size: 72px; max-block-size: 72px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--site-color) 28%, transparent); border-inline-start: 4px solid var(--site-color); border-radius: var(--app-control-radius); color: inherit; background: color-mix(in srgb, var(--site-color) 5%, transparent); font: inherit; text-align: start; cursor: pointer; }
.site-item:hover { background: color-mix(in srgb, var(--site-color) 10%, transparent); }
.site-item--active { border-color: color-mix(in srgb, var(--site-color) 48%, transparent); border-inline-start-color: var(--site-color); background: color-mix(in srgb, var(--site-color) 14%, transparent); }
.site-add { border-style: dashed; }
.site-item span { display: flex; align-items: center; gap: 8px; overflow-wrap: anywhere; }
.site-item i { inline-size: 8px; block-size: 8px; flex: 0 0 auto; border-radius: 50%; background: rgb(var(--v-theme-secondary)); }
.site-item i.online { background: var(--site-color); }
.site-item small, .block-muted, .task-name small { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.workspace { min-inline-size: 0; }
.mobile-site { display: none; }
.site-head { min-block-size: 52px; }
.site-head__name { flex: 1 1 auto; gap: 8px; min-inline-size: 0; }
.site-head__name :deep(.v-text-field) { max-inline-size: 28rem; }
.site-head__name :deep(.v-field__input) { font-size: 1rem; font-weight: 600; }
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
.progress-cell { display: flex; flex-direction: column; align-items: stretch; gap: 6px; min-inline-size: 7rem; }
.block-muted { display: block; font-size: .78rem; }
.empty-table { padding: 28px 12px; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); text-align: center; }
.empty-state { display: grid; place-items: center; align-content: center; gap: 12px; min-block-size: 18rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.rule-list { margin-block-start: 8px; }
.rule-title { min-inline-size: 0; flex-wrap: wrap; }
.rule-title strong { overflow-wrap: anywhere; }
.rule-grid, .settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding-block: 8px; }
.span-2 { grid-column: 1 / -1; }
.range-control { display: flex; flex-direction: column; gap: 7px; min-inline-size: 0; }
.range-control > span { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: .8rem; }
.range-fields { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 8px; }
.range-fields b { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-weight: 400; }
.value-unit { display: grid; grid-template-columns: minmax(5.5rem, 1fr) minmax(6rem, .8fr); gap: 6px; min-inline-size: 0; }
.rule-actions { margin-block-start: 12px; }
.cleanup-list { display: flex; flex-direction: column; gap: 10px; }
.cleanup-rule { display: grid; grid-template-columns: 32px minmax(0, 1fr) 36px; align-items: center; gap: 12px; padding: 14px; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: var(--app-control-radius); }
.order { display: grid; place-items: center; inline-size: 28px; block-size: 28px; border-radius: 50%; color: rgb(var(--v-theme-on-primary)); background: rgb(var(--v-theme-primary)); font-size: .8rem; }
.cleanup-fields { display: grid; grid-template-columns: 1.1fr 1.5fr repeat(2, minmax(9rem, .7fr)) auto auto; align-items: center; gap: 10px; min-inline-size: 0; }
.vertical-actions { display: flex; flex-direction: column; gap: 2px; }
.history-list { display: flex; flex-direction: column; }
.history-list article { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 12px; padding: 12px 4px; border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.history-list article > div { display: flex; flex-direction: column; min-inline-size: 0; }
.history-list article strong, .history-list article a, .history-list article span { overflow-wrap: anywhere; }
.history-list article a { color: rgb(var(--v-theme-primary)); font-weight: 600; text-decoration: none; }
.history-list article a:hover { text-decoration: underline; }
.history-list article span, .history-list time { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: .8rem; }
.history-list article span b { color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity)); font-weight: 600; }
.history-list article .history-result { color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity)); }
.settings-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-block-start: 18px; }
@media (max-width: 1199px) { .cleanup-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (min-width: 960px) { .tracker--compact { block-size: calc(100dvh - 48px); min-block-size: 0; overflow: hidden; } .tracker--compact .tracker__layout { flex: 1 1 auto; min-block-size: 0; overflow: hidden; } .tracker--compact .site-rail { position: static; block-size: 100%; max-block-size: none; } .tracker--compact .workspace { block-size: 100%; padding-inline-end: 4px; overflow-y: auto; } }
@media (max-width: 959px) { .tracker { padding: 12px; } .site-rail { display: none; } .mobile-site { display: block; margin-block-end: 12px; } .tracker__layout { grid-template-columns: 1fr; } .rule-grid, .settings-grid { grid-template-columns: 1fr; } .span-2 { grid-column: auto; } }
@media (max-width: 699px) { .tracker__identity p, .global-settings-label { display: none; } .tracker__actions { flex-wrap: nowrap; } .site-head { align-items: flex-start; flex-direction: column; } .site-head__actions { inline-size: 100%; justify-content: space-between; } .panel__head { flex-direction: column; } .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .cleanup-rule { grid-template-columns: 28px minmax(0, 1fr); } .vertical-actions { grid-column: 2; flex-direction: row; } .cleanup-fields { grid-template-columns: 1fr; } .range-fields--units { grid-template-columns: 1fr; } .range-fields--units > b { text-align: center; } .value-unit { grid-template-columns: minmax(0, 1fr) minmax(6rem, .65fr); } .history-list article { grid-template-columns: auto minmax(0, 1fr); } .history-list time { grid-column: 2; } }
.sync-note, .operation-hint { color: rgba(var(--v-theme-on-surface), .7); font-size: .8rem; overflow-wrap: anywhere; }
.operation-hint { margin-block: 0 14px; }
.operation-actions { flex-wrap: wrap; }
.job-status { display: grid; gap: 8px; padding: 12px; border-radius: 8px; background: rgba(var(--v-theme-primary), .08); font-size: .85rem; }
.job-status > div { display: flex; align-items: center; gap: 8px; }
.job-status span { overflow-wrap: anywhere; }
.list-filters { display: grid; grid-template-columns: minmax(0, 2fr) repeat(2, minmax(0, 1fr)); gap: 12px; margin-block-end: 16px; }
.history-filters { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
.list-filters > *, .rule-grid > *, .settings-grid > *, .cleanup-fields > * { min-inline-size: 0; }
.list-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; padding-block-start: 16px; font-size: .8rem; }
.list-pagination > :deep(.v-input) { flex: 0 0 86px; }
.task-table-wrap { max-inline-size: 100%; overflow-x: auto; }
.task-table :deep(table) { min-inline-size: 940px; table-layout: fixed; }
.task-table :deep(td) { padding-block: 12px !important; vertical-align: top; }
.task-table :deep(.v-data-table__wrapper), .task-table :deep(.v-table__wrapper) { overflow-x: auto; }
.task-cards { display: none; }
.task-name { min-inline-size: 15rem; }
.rule-title { flex-wrap: nowrap; inline-size: 100%; }
.rule-title__text { flex: 1; min-inline-size: 0; }
.rule-title__text strong, .rule-title__text small { display: block; overflow-wrap: anywhere; }
.rule-title__text small { margin-block-start: 5px; font-size: .76rem; line-height: 1.5; color: rgba(var(--v-theme-on-surface), .7); }
.cleanup-summary { grid-column: 1 / -1; margin: 0; overflow-wrap: anywhere; color: rgba(var(--v-theme-on-surface), .7); font-size: .8rem; }
.save-bar { position: sticky; bottom: 0; z-index: 4; display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 12px; padding-block-end: max(12px, env(safe-area-inset-bottom)); border: 1px solid rgba(var(--v-theme-primary), .3); border-radius: 10px; background: rgb(var(--v-theme-surface)); box-shadow: 0 -3px 12px rgba(0, 0, 0, .08); font-size: .85rem; }
.save-bar > div { display: flex; gap: 8px; }
.global-settings-button { min-inline-size: 40px; }
.auth-alert { margin-block-start: 16px; }
@media (max-width: 959px) {
  .mobile-site { display: flex; align-items: center; gap: 8px; }
  .mobile-site > :deep(.v-input) { flex: 1; min-inline-size: 0; }
  .site-head__name { inline-size: 100%; }
}
@media (max-width: 699px) {
  .tracker__header { flex-wrap: wrap; gap: 6px; }
  .tracker__identity { gap: 6px; }
  .tracker__identity h1 { font-size: 1.1rem; }
  .tracker__actions { margin-inline-start: auto; gap: 2px; }
  .tracker__actions :deep(.v-btn) { padding-inline: 8px; }
  .panel { padding: 12px; }
  .task-table-wrap { display: none; }
  .task-cards { display: grid; gap: 12px; }
  .task-card { min-inline-size: 0; padding: 14px; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 10px; }
  .task-card__meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-block: 8px 14px; font-size: .78rem; overflow-wrap: anywhere; }
  .task-card__progress { display: grid; gap: 6px; inline-size: 100%; font-size: .8rem; }
  .task-card__progress > div:first-child { display: flex; justify-content: space-between; }
  .task-card__metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-block: 14px; font-size: .8rem; overflow-wrap: anywhere; }
  .task-card__deadline { font-size: .85rem; }
  .task-card__reason { margin-block: 10px 0; color: rgba(var(--v-theme-on-surface), .7); font-size: .78rem; overflow-wrap: anywhere; }
  .list-filters, .history-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .list-filters > :first-child { grid-column: 1 / -1; }
  .history-filters { grid-template-columns: 1fr; }
  .list-pagination { justify-content: center; }
  .list-pagination > :deep(.v-pagination) { flex-basis: 100%; }
  .rule-actions { flex-wrap: wrap; }
  .save-bar > span { flex-basis: 100%; }
  .save-bar > div { margin-inline-start: auto; }
}
</style>
