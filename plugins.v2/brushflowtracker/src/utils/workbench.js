export const clone = value => JSON.parse(JSON.stringify(value ?? {}))
export const fingerprint = value => JSON.stringify(value)
export const uid = () => globalThis.crypto?.randomUUID?.().replaceAll('-', '') || `${Date.now()}${Math.random()}`.replace('.', '')
export const operationNames = { rss: '刷新 RSS', cleanup: '执行删种', free_monitor: '检查免费期' }
export const proxyOptions = [{ title: '继承站点', value: null }, { title: '开启代理', value: true }, { title: '关闭代理', value: false }]
export const promotionOptions = [{ title: '不限促销', value: 'any' }, { title: '仅免费', value: 'free' }, { title: '免费或双倍上传免费', value: 'free_or_2xfree' }, { title: '仅双倍上传免费', value: '2xfree' }]
export const timeUnitOptions = [{ title: '秒', value: 'seconds' }, { title: '分钟', value: 'minutes' }, { title: '小时', value: 'hours' }, { title: '天', value: 'days' }]
export const sizeUnitOptions = [{ title: 'KB', value: 'kib' }, { title: 'MB', value: 'mib' }, { title: 'GB', value: 'gib' }, { title: 'TB', value: 'tib' }]
export const resolutionOptions = ['8K', '4K', '1080P', '1080I', '720P', '576P', '480P']

export function unwrap(response) {
  if (response?.success === false) {
    const error = new Error(response.message || '操作失败')
    error.detail = response.detail || response.data?.detail
    throw error
  }
  return response?.data ?? response
}

// Each resource has its own gate: an old error/finally must not alter a newer request.
export function requestGate() {
  let generation = 0
  return {
    begin: scope => ({ generation: ++generation, scope }),
    current: (ticket, scope) => ticket.generation === generation && ticket.scope === scope,
    invalidate: () => { generation += 1 },
  }
}

export function prepareSettings(settings) {
  const payload = clone(settings)
  for (const site of payload.sites || []) {
    for (const rule of site.rss_rules || []) {
      for (const key of ['publish_age_from_value', 'publish_age_to_value', 'size_from_value', 'size_to_value']) {
        if (rule[key] === '' || rule[key] === undefined) rule[key] = null
      }
      if (rule.use_proxy === undefined) rule.use_proxy = null
    }
    // Empty is deliberately NOT expanded to all tasks.
    for (const rule of site.cleanup_rules || []) if (!(rule.labels || []).length) rule.enabled = false
  }
  return payload
}

export function removeRssAndDisableReferences(site, index) {
  const [removed] = site.rss_rules.splice(index, 1)
  const affected = []
  for (const rule of site.cleanup_rules || []) {
    if ((rule.labels || []).includes(removed?.name)) {
      rule.labels = rule.labels.filter(label => label !== removed.name)
      rule.enabled = false
      affected.push(rule.name)
    }
  }
  return affected
}

export function saveResolution(currentDraft, currentRevision, sentRevision, responseSettings, sentPayload) {
  const saved = clone(responseSettings || sentPayload)
  return { saved, draft: currentRevision === sentRevision ? clone(saved) : currentDraft }
}

export function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0)
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.max(0, Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1))
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`
}
export function formatTime(value) {
  if (!value) return '尚未刷新'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
export function formatDuration(seconds) {
  const hours = Math.floor((Number(seconds) || 0) / 3600)
  return hours >= 24 ? `${Math.floor(hours / 24)} 天 ${hours % 24} 小时` : `${hours} 小时`
}
export const taskTags = item => Array.isArray(item.tags) ? item.tags : String(item.tags || '').split(',').map(t => t.trim()).filter(Boolean)
export const taskProgress = item => Math.max(0, Math.min(100, Number(item.progress) || 0))
export function taskState(item) {
  const state = String(item.state || '')
  if (/^(paused|stopped)/i.test(state)) return { key: 'paused', title: '已暂停', color: 'warning' }
  if (/error|missingFiles/i.test(state)) return { key: 'error', title: state === 'missingFiles' ? '文件缺失' : '任务错误', color: 'error' }
  if (/checking|moving/i.test(state)) return { key: 'checking', title: state === 'moving' ? '移动文件' : '校验中', color: 'info' }
  if (/queued/i.test(state)) return { key: 'queued', title: /UP/i.test(state) ? '排队做种' : '排队下载', color: 'secondary' }
  if (/metaDL/i.test(state)) return { key: 'downloading', title: '获取元数据', color: 'info' }
  if (/stalledDL/i.test(state)) return { key: 'downloading', title: '等待下载', color: 'warning' }
  if (/downloading|forcedDL|allocating/i.test(state)) return { key: 'downloading', title: state === 'allocating' ? '分配空间' : '下载中', color: 'primary' }
  if (/uploading|stalledUP|forcedUP/i.test(state)) return { key: 'seeding', title: state === 'stalledUP' ? '等待上传' : '做种中', color: 'success' }
  return { key: 'other', title: '未知状态', color: 'default' }
}
export function pauseExplanation(item) {
  if (item.pause_reason) return item.pause_reason
  if (item.paused_by_plugin) return '插件暂停并保留文件，等待替换或恢复'
  if (taskState(item).key === 'paused') return '下载器已暂停；未提供暂停来源，不能确定是否由用户操作'
  if (item.replacement_for?.length) return '替换下载中，旧版本在完成确认前保留'
  return ''
}
export function freeRemaining(value, now = Date.now()) {
  if (!value) return { text: '未提供免费截止', urgent: false }
  const remaining = new Date(value).getTime() - now
  if (!Number.isFinite(remaining)) return { text: '免费截止未知', urgent: false }
  if (remaining <= 0) return { text: '免费期已结束', urgent: true }
  const minutes = Math.ceil(remaining / 60000)
  const text = minutes >= 1440 ? `${Math.floor(minutes / 1440)}天 ${Math.floor(minutes % 1440 / 60)}小时` : minutes >= 60 ? `${Math.floor(minutes / 60)}小时 ${minutes % 60}分钟` : `${minutes}分钟`
  return { text: `免费剩余 ${text}`, urgent: minutes <= 60 }
}
export function ruleSummary(rule) {
  const range = (from, to, units) => {
    const label = key => units.find(u => u.value === rule[key])?.title || ''
    const start = rule[`${from}_value`], end = rule[`${to}_value`]
    const missing = value => value == null || value === ''
    if (missing(start) && missing(end)) return '不限'
    return `${missing(start) ? 0 : start}${label(`${from}_unit`)}–${missing(end) ? '不限' : `${end}${label(`${to}_unit`)}`}`
  }
  return [(rule.resolutions || []).join('/') || '最高画质', `时间 ${range('publish_age_from', 'publish_age_to', timeUnitOptions)}`, `体积 ${range('size_from', 'size_to', sizeUnitOptions)}`, promotionOptions.find(p => p.value === rule.promotion)?.title || '不限促销'].join(' · ')
}

// Status currently returns an operation-keyed object; tolerate array responses too.
export function normalizeJobs(value) {
  if (Array.isArray(value)) return Object.fromEntries(value.filter(job => job?.operation).map(job => [job.operation, job]))
  return value && typeof value === 'object' ? value : {}
}
export function reconcileJobs(pending, running, now = Date.now(), queueGrace = 30000) {
  const next = {}, finished = [], unconfirmed = []
  for (const [operation, entry] of Object.entries(pending)) {
    const job = running[operation]
    if (job && (!job.site_id || job.site_id === entry.site_id)) next[operation] = { ...entry, observed: true }
    else if (entry.observed) finished.push(operation)
    else if (now - entry.submitted_at < queueGrace) next[operation] = entry
    else unconfirmed.push(operation)
  }
  return { pending: next, finished, unconfirmed }
}

// Validate even unmounted tabs, before submitting a full configuration.
export function validateSettings(settings) {
  const number = (value, min, max = Infinity) => value !== '' && value != null && Number.isFinite(Number(value)) && Number(value) >= min && Number(value) <= max
  for (const [key, label, min, max] of [
    ['rss_interval_minutes', 'RSS 刷新间隔', 1, 10080], ['free_monitor_interval_minutes', '免费期检查间隔', 1, 1440],
    ['cleanup_interval_minutes', '自动删种间隔', 1, 10080], ['request_timeout_seconds', 'RSS 请求超时', 5, 120],
    ['history_limit', '历史记录上限', 50, 5000], ['dead_seed_wait_minutes', '死种等待时间', 1, 10080],
    ['dead_seed_min_seeders', '最低做种数', 0, 1000],
  ]) {
    if (settings[key] !== undefined && (!number(settings[key], min, max) || !Number.isInteger(Number(settings[key])))) return { tab: 'settings', message: `${label}必须是 ${min}–${max} 的整数` }
  }
  for (const site of settings.sites || []) {
    const fail = (message, tab = 'rss') => ({ siteId: site.id, tab, message: `${site.name || '未命名站点'}：${message}` })
    if (!String(site.name || '').trim()) return fail('站点名称不能为空', 'site')
    const names = new Set()
    for (const rule of site.rss_rules || []) {
      const name = String(rule.name || '').trim()
      if (!name || name.includes(',')) return fail('RSS 任务名称不能为空或包含英文逗号')
      if (names.has(name)) return fail(`RSS 任务名称重复：${name}`)
      names.add(name)
      if (rule.url && !/^https?:\/\//i.test(rule.url.trim())) return fail(`${name} 的订阅地址必须使用 HTTP(S)`)
      for (const [from, to, units, label] of [
        ['publish_age_from', 'publish_age_to', { seconds: 1, minutes: 60, hours: 3600, days: 86400 }, '发种时间'],
        ['size_from', 'size_to', { kib: 1, mib: 1024, gib: 1024 ** 2, tib: 1024 ** 3 }, '体积'],
      ]) {
        const a = rule[`${from}_value`], b = rule[`${to}_value`]
        const present = value => value !== '' && value != null
        if ([a, b].some(value => present(value) && !number(value, 0))) return fail(`${name} 的${label}必须是非负数`)
        if (present(a) && present(b) && Number(a) * units[rule[`${from}_unit`]] > Number(b) * units[rule[`${to}_unit`]]) return fail(`${name} 的${label}范围起点不能大于终点`)
      }
    }
    for (const rule of site.cleanup_rules || []) {
      if (!number(rule.min_seed_hours ?? 0, 0) || !number(rule.min_ratio ?? 0, 0)) return fail(`${rule.name} 的做种时长和分享率必须是非负数`, 'cleanup')
      if (rule.enabled && !(rule.labels || []).length) return fail(`${rule.name} 未选择任务标签，请选择标签或停用规则`, 'cleanup')
      if (rule.enabled && rule.labels.some(label => !names.has(label))) return fail(`${rule.name} 包含失效的任务标签，请修复或停用规则`, 'cleanup')
    }
  }
  return null
}
