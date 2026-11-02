import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {toDisplayString:_toDisplayString$1,normalizeClass:_normalizeClass$1,createElementVNode:_createElementVNode$1,openBlock:_openBlock$1,createElementBlock:_createElementBlock$1} = await importShared('vue');


const _hoisted_1$1 = { class: "task-title" };
const _hoisted_2$1 = ["aria-expanded", "aria-label"];

const {ref: ref$1,watch: watch$1} = await importShared('vue');


const _sfc_main$1 = {
  __name: 'TaskTitle',
  props: { name: { type: String, default: '未命名任务' } },
  setup(__props) {

const props = __props;
const expanded = ref$1(false);
watch$1(() => props.name, () => { expanded.value = false; });

return (_ctx, _cache) => {
  return (_openBlock$1(), _createElementBlock$1("div", _hoisted_1$1, [
    _createElementVNode$1("strong", {
      class: _normalizeClass$1({ 'task-title--clamped': !expanded.value })
    }, _toDisplayString$1(__props.name || '未命名任务'), 3),
    _createElementVNode$1("button", {
      type: "button",
      "aria-expanded": expanded.value,
      "aria-label": `${expanded.value ? '收起' : '展开'}任务名称：${__props.name}`,
      onClick: _cache[0] || (_cache[0] = $event => (expanded.value = !expanded.value))
    }, _toDisplayString$1(expanded.value ? '收起名称' : '展开名称'), 9, _hoisted_2$1)
  ]))
}
}

};
const TaskTitle = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-d2e5265b"]]);

const clone = value => JSON.parse(JSON.stringify(value ?? {}));
const fingerprint = value => JSON.stringify(value);
const uid = () => globalThis.crypto?.randomUUID?.().replaceAll('-', '') || `${Date.now()}${Math.random()}`.replace('.', '');
const operationNames = { rss: '刷新 RSS', cleanup: '执行删种', free_monitor: '检查免费期' };
const proxyOptions = [{ title: '继承站点', value: null }, { title: '开启代理', value: true }, { title: '关闭代理', value: false }];
const promotionOptions = [{ title: '不限促销', value: 'any' }, { title: '仅免费', value: 'free' }, { title: '免费或双倍上传免费', value: 'free_or_2xfree' }, { title: '仅双倍上传免费', value: '2xfree' }];
const timeUnitOptions = [{ title: '秒', value: 'seconds' }, { title: '分钟', value: 'minutes' }, { title: '小时', value: 'hours' }, { title: '天', value: 'days' }];
const sizeUnitOptions = [{ title: 'KB', value: 'kib' }, { title: 'MB', value: 'mib' }, { title: 'GB', value: 'gib' }, { title: 'TB', value: 'tib' }];
const resolutionOptions = ['8K', '4K', '1080P', '1080I', '720P', '576P', '480P'];

function unwrap(response) {
  if (response?.success === false) {
    const error = new Error(response.message || '操作失败');
    error.detail = response.detail || response.data?.detail;
    throw error
  }
  return response?.data ?? response
}

// Each resource has its own gate: an old error/finally must not alter a newer request.
function requestGate() {
  let generation = 0;
  return {
    begin: scope => ({ generation: ++generation, scope }),
    current: (ticket, scope) => ticket.generation === generation && ticket.scope === scope,
    invalidate: () => { generation += 1; },
  }
}

function prepareSettings(settings) {
  const payload = clone(settings);
  for (const site of payload.sites || []) {
    for (const rule of site.rss_rules || []) {
      for (const key of ['publish_age_from_value', 'publish_age_to_value', 'size_from_value', 'size_to_value']) {
        if (rule[key] === '' || rule[key] === undefined) rule[key] = null;
      }
      if (rule.use_proxy === undefined) rule.use_proxy = null;
    }
    // Empty is deliberately NOT expanded to all tasks.
    for (const rule of site.cleanup_rules || []) if (!(rule.labels || []).length) rule.enabled = false;
  }
  return payload
}

function removeRssAndDisableReferences(site, index) {
  const [removed] = site.rss_rules.splice(index, 1);
  const affected = [];
  for (const rule of site.cleanup_rules || []) {
    if ((rule.labels || []).includes(removed?.name)) {
      rule.labels = rule.labels.filter(label => label !== removed.name);
      rule.enabled = false;
      affected.push(rule.name);
    }
  }
  return affected
}

function saveResolution(currentDraft, currentRevision, sentRevision, responseSettings, sentPayload) {
  const saved = clone(responseSettings || sentPayload);
  return { saved, draft: currentRevision === sentRevision ? clone(saved) : currentDraft }
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.max(0, Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1));
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`
}
function formatTime(value) {
  if (!value) return '尚未刷新'
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function formatDuration(seconds) {
  const hours = Math.floor((Number(seconds) || 0) / 3600);
  return hours >= 24 ? `${Math.floor(hours / 24)} 天 ${hours % 24} 小时` : `${hours} 小时`
}
const taskTags = item => Array.isArray(item.tags) ? item.tags : String(item.tags || '').split(',').map(t => t.trim()).filter(Boolean);
const taskProgress = item => Math.max(0, Math.min(100, Number(item.progress) || 0));
function taskState(item) {
  const state = String(item.state || '');
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
function pauseExplanation(item) {
  if (item.pause_reason) return item.pause_reason
  if (item.paused_by_plugin) return '插件暂停并保留文件，等待替换或恢复'
  if (taskState(item).key === 'paused') return '下载器已暂停；未提供暂停来源，不能确定是否由用户操作'
  if (item.replacement_for?.length) return '替换下载中，旧版本在完成确认前保留'
  return ''
}
function freeRemaining(value, now = Date.now()) {
  if (!value) return { text: '未提供免费截止', urgent: false }
  const remaining = new Date(value).getTime() - now;
  if (!Number.isFinite(remaining)) return { text: '免费截止未知', urgent: false }
  if (remaining <= 0) return { text: '免费期已结束', urgent: true }
  const minutes = Math.ceil(remaining / 60000);
  const text = minutes >= 1440 ? `${Math.floor(minutes / 1440)}天 ${Math.floor(minutes % 1440 / 60)}小时` : minutes >= 60 ? `${Math.floor(minutes / 60)}小时 ${minutes % 60}分钟` : `${minutes}分钟`;
  return { text: `免费剩余 ${text}`, urgent: minutes <= 60 }
}
function ruleSummary(rule) {
  const range = (from, to, units) => {
    const label = key => units.find(u => u.value === rule[key])?.title || '';
    const start = rule[`${from}_value`], end = rule[`${to}_value`];
    const missing = value => value == null || value === '';
    if (missing(start) && missing(end)) return '不限'
    return `${missing(start) ? 0 : start}${label(`${from}_unit`)}–${missing(end) ? '不限' : `${end}${label(`${to}_unit`)}`}`
  };
  return [(rule.resolutions || []).join('/') || '最高画质', `时间 ${range('publish_age_from', 'publish_age_to', timeUnitOptions)}`, `体积 ${range('size_from', 'size_to', sizeUnitOptions)}`, promotionOptions.find(p => p.value === rule.promotion)?.title || '不限促销'].join(' · ')
}

// Status currently returns an operation-keyed object; tolerate array responses too.
function normalizeJobs(value) {
  if (Array.isArray(value)) return Object.fromEntries(value.filter(job => job?.operation).map(job => [job.operation, job]))
  return value && typeof value === 'object' ? value : {}
}
function reconcileJobs(pending, running, now = Date.now(), queueGrace = 30000) {
  const next = {}, finished = [], unconfirmed = [];
  for (const [operation, entry] of Object.entries(pending)) {
    const job = running[operation];
    if (job && (!job.site_id || job.site_id === entry.site_id)) next[operation] = { ...entry, observed: true };
    else if (entry.observed) finished.push(operation);
    else if (now - entry.submitted_at < queueGrace) next[operation] = entry;
    else unconfirmed.push(operation);
  }
  return { pending: next, finished, unconfirmed }
}

// Validate even unmounted tabs, before submitting a full configuration.
function validateSettings(settings) {
  const number = (value, min, max = Infinity) => value !== '' && value != null && Number.isFinite(Number(value)) && Number(value) >= min && Number(value) <= max;
  for (const [key, label, min, max] of [
    ['rss_interval_minutes', 'RSS 刷新间隔', 1, 10080], ['free_monitor_interval_minutes', '免费期检查间隔', 1, 1440],
    ['cleanup_interval_minutes', '自动删种间隔', 1, 10080], ['request_timeout_seconds', 'RSS 请求超时', 5, 120],
    ['history_limit', '历史记录上限', 50, 5000], ['dead_seed_wait_minutes', '死种等待时间', 1, 10080],
    ['dead_seed_min_seeders', '最低做种数', 0, 1000],
  ]) {
    if (settings[key] !== undefined && (!number(settings[key], min, max) || !Number.isInteger(Number(settings[key])))) return { tab: 'settings', message: `${label}必须是 ${min}–${max} 的整数` }
  }
  for (const site of settings.sites || []) {
    const fail = (message, tab = 'rss') => ({ siteId: site.id, tab, message: `${site.name || '未命名站点'}：${message}` });
    if (!String(site.name || '').trim()) return fail('站点名称不能为空', 'site')
    const names = new Set();
    for (const rule of site.rss_rules || []) {
      const name = String(rule.name || '').trim();
      if (!name || name.includes(',')) return fail('RSS 任务名称不能为空或包含英文逗号')
      if (names.has(name)) return fail(`RSS 任务名称重复：${name}`)
      names.add(name);
      if (rule.url && !/^https?:\/\//i.test(rule.url.trim())) return fail(`${name} 的订阅地址必须使用 HTTP(S)`)
      for (const [from, to, units, label] of [
        ['publish_age_from', 'publish_age_to', { seconds: 1, minutes: 60, hours: 3600, days: 86400 }, '发种时间'],
        ['size_from', 'size_to', { kib: 1, mib: 1024, gib: 1024 ** 2, tib: 1024 ** 3 }, '体积'],
      ]) {
        const a = rule[`${from}_value`], b = rule[`${to}_value`];
        const present = value => value !== '' && value != null;
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

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,mergeProps:_mergeProps,withCtx:_withCtx,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment,unref:_unref,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "tracker__header" };
const _hoisted_2 = { class: "tracker__identity" };
const _hoisted_3 = { class: "tracker__actions" };
const _hoisted_4 = { key: 0 };
const _hoisted_5 = {
  key: 7,
  class: "job-status",
  role: "status",
  "aria-live": "polite"
};
const _hoisted_6 = { class: "sync-note" };
const _hoisted_7 = {
  key: 8,
  class: "tracker__loading"
};
const _hoisted_8 = {
  key: 9,
  class: "tracker__layout"
};
const _hoisted_9 = { class: "site-list" };
const _hoisted_10 = ["onClick"];
const _hoisted_11 = ["disabled"];
const _hoisted_12 = { class: "workspace" };
const _hoisted_13 = { class: "mobile-site" };
const _hoisted_14 = {
  key: 0,
  class: "site-head"
};
const _hoisted_15 = { class: "site-head__name" };
const _hoisted_16 = { class: "site-head__actions" };
const _hoisted_17 = { class: "stats" };
const _hoisted_18 = { class: "panel__head" };
const _hoisted_19 = { class: "operation-actions" };
const _hoisted_20 = { class: "operation-hint" };
const _hoisted_21 = { class: "list-filters" };
const _hoisted_22 = {
  key: 1,
  class: "empty-table"
};
const _hoisted_23 = { class: "task-table-wrap" };
const _hoisted_24 = { class: "task-name" };
const _hoisted_25 = { key: 0 };
const _hoisted_26 = { class: "progress-cell" };
const _hoisted_27 = { class: "block-muted" };
const _hoisted_28 = { class: "block-muted" };
const _hoisted_29 = {
  key: 0,
  class: "block-muted"
};
const _hoisted_30 = { class: "task-cards" };
const _hoisted_31 = { class: "task-card__meta" };
const _hoisted_32 = { class: "task-card__progress" };
const _hoisted_33 = { class: "task-card__metrics" };
const _hoisted_34 = {
  key: 0,
  class: "block-muted"
};
const _hoisted_35 = {
  key: 0,
  class: "task-card__reason"
};
const _hoisted_36 = { class: "list-pagination" };
const _hoisted_37 = { class: "panel__head" };
const _hoisted_38 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_39 = { class: "rule-title" };
const _hoisted_40 = { class: "rule-title__text" };
const _hoisted_41 = { class: "rule-grid" };
const _hoisted_42 = { class: "range-control" };
const _hoisted_43 = { class: "range-fields range-fields--units" };
const _hoisted_44 = { class: "value-unit" };
const _hoisted_45 = { class: "value-unit" };
const _hoisted_46 = { class: "range-control" };
const _hoisted_47 = { class: "range-fields range-fields--units" };
const _hoisted_48 = { class: "value-unit" };
const _hoisted_49 = { class: "value-unit" };
const _hoisted_50 = { class: "rule-actions" };
const _hoisted_51 = { class: "panel__head" };
const _hoisted_52 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_53 = {
  key: 1,
  class: "cleanup-list"
};
const _hoisted_54 = { class: "order" };
const _hoisted_55 = { class: "cleanup-fields" };
const _hoisted_56 = { class: "cleanup-summary" };
const _hoisted_57 = { class: "vertical-actions" };
const _hoisted_58 = { class: "list-filters history-filters" };
const _hoisted_59 = { class: "history-list" };
const _hoisted_60 = ["href"];
const _hoisted_61 = { key: 1 };
const _hoisted_62 = { class: "history-result" };
const _hoisted_63 = { key: 2 };
const _hoisted_64 = { key: 3 };
const _hoisted_65 = {
  key: 0,
  class: "empty-table"
};
const _hoisted_66 = { class: "list-pagination" };
const _hoisted_67 = { class: "settings-grid" };
const _hoisted_68 = { class: "settings-grid" };
const _hoisted_69 = { class: "operation-hint" };
const _hoisted_70 = { class: "settings-actions" };
const _hoisted_71 = {
  key: 1,
  class: "empty-state empty-workspace"
};
const _hoisted_72 = { class: "rule-grid auth-grid" };
const _hoisted_73 = {
  key: 10,
  class: "save-bar",
  role: "status"
};

const {computed,inject,nextTick,onBeforeUnmount,onMounted,ref,watch} = await importShared('vue');

const POLL_BUDGET = 15 * 60 * 1000;

const pluginBase = 'plugin/BrushFlowTracker';

const _sfc_main = {
  __name: 'Workbench',
  props: {
  api: { type: Object, default: () => ({}) },
  initialTab: { type: String, default: 'tasks' },
  compact: { type: Boolean, default: false },
  showClose: { type: Boolean, default: false },
},
  emits: ['action', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const hostToast = inject('moviepilot:toast', null);
const loading = ref(true);
const tasksLoading = ref(false);
const saving = ref(false);
const testing = ref(false);
const runSubmitting = ref({});
const pendingJobs = ref({});
const settingsLoaded = ref(false);
const statusError = ref('');
const error = ref('');
const message = ref('');
const messageKind = ref('success');
const messageOpen = ref(false);
const referenceWarning = ref('');
const pollWarning = ref('');
const lastSynced = ref(null);
const now = ref(Date.now());
const settingsForm = ref(null);
const activeTab = ref(props.initialTab);
const selectedSiteId = ref('');
const deleteSiteDialog = ref(false);
const discardDialog = ref(false);
const leaveDialog = ref(false);
const cleanupDialog = ref(false);
const cleanupTarget = ref(null);
const authRuleId = ref(null);
const status = ref({ settings: { sites: [] }, sites: [], tasks: [], history: [], downloaders: [], running_jobs: {} });
const draft = ref({ sites: [] });
const savedSettings = ref({ sites: [] });
const draftRevision = ref(0);
const statusGate = requestGate();
const tasksGate = requestGate();
let configEpoch = 0;
let replacingDraft = false;
let mounted = false;
let disposed = false;
let pollTimer = null;
let clockTimer = null;
let pollDeadline = 0;
let pollFailures = 0;
let lastTaskPoll = 0;
const sites = computed(() => draft.value.sites || []);
const selectedSite = computed(() => sites.value.find(site => site.id === selectedSiteId.value) || null);
const savedSite = computed(() => savedSettings.value.sites?.find(site => site.id === selectedSiteId.value) || null);
const selectedSummary = computed(() => status.value.sites?.find(site => site.id === selectedSiteId.value) || {});
const authRule = computed(() => selectedSite.value?.rss_rules?.find(rule => rule.id === authRuleId.value) || null);
const authDialog = computed({
  get: () => Boolean(authRule.value),
  set: value => { if (!value) authRuleId.value = null; },
});
const taskNameOptions = computed(() => selectedSite.value?.rss_rules?.map(rule => rule.name).filter(Boolean) || []);
const dirty = computed(() => settingsLoaded.value && fingerprint(draft.value) !== fingerprint(savedSettings.value));
const canSave = computed(() => settingsLoaded.value && !statusError.value && !loading.value && !saving.value && dirty.value);
const runDisabledReason = computed(() => {
  if (!settingsLoaded.value || statusError.value) return '配置未成功加载，暂不能执行'
  if (saving.value) return '正在保存，请等待保存完成'
  if (dirty.value) return '有未保存修改，请先保存；手动运行只使用服务器已保存配置'
  if (status.value.config_pending) return '设置已保存，将在当前后台任务结束后生效'
  if (Object.keys(status.value.running_jobs || {}).length) return '已有后台任务正在执行，请等待本轮完成'
  if (!savedSite.value) return '请先创建并保存站点'
  return ''
});
const jobs = computed(() => normalizeJobs(status.value.running_jobs));
const jobRows = computed(() => Object.entries({ ...pendingJobs.value, ...jobs.value }).map(([operation, job]) => ({
  ...job, operation,
  name: operationNames[operation] || operation,
  siteName: job.site_id ? savedSettings.value.sites?.find(site => site.id === job.site_id)?.name || '其他站点' : '全部站点',
  pending: !jobs.value[operation],
})));
const downloaderLabel = computed(() => savedSettings.value.downloader_mode === 'custom'
  ? (savedSettings.value.custom_qb_url || '自定义 qBittorrent')
  : (savedSettings.value.downloader || '尚未选择下载器'));
const taskSearch = ref('');
const taskStateFilter = ref('all');
const taskRuleFilter = ref(null);
const taskPage = ref(1);
const taskPageSize = ref(10);
const historySearch = ref('');
const historyFilter = ref('all');
const historyPage = ref(1);
const historyPageSize = ref(20);
const stateOptions = [
  { title: '全部状态', value: 'all' }, { title: '下载中', value: 'downloading' },
  { title: '做种中', value: 'seeding' }, { title: '已暂停', value: 'paused' },
  { title: '排队中', value: 'queued' }, { title: '校验 / 移动', value: 'checking' },
  { title: '任务错误', value: 'error' }, { title: '其他状态', value: 'other' },
];
const taskFilterOptions = computed(() => [...new Set([...(savedSite.value?.rss_rules || []).map(rule => rule.name), ...(status.value.tasks || []).flatMap(taskTags)])].filter(Boolean));
const filteredTasks = computed(() => (status.value.tasks || []).filter(item => {
  const query = taskSearch.value.trim().toLocaleLowerCase();
  return (!query || `${item.name || ''} ${taskTags(item).join(' ')} ${item.hash || ''}`.toLocaleLowerCase().includes(query))
    && (taskStateFilter.value === 'all' || taskState(item).key === taskStateFilter.value)
    && (!taskRuleFilter.value || taskTags(item).includes(taskRuleFilter.value))
}));
const taskPageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / taskPageSize.value)));
const pagedTasks = computed(() => filteredTasks.value.slice((taskPage.value - 1) * taskPageSize.value, taskPage.value * taskPageSize.value));
const historyOptions = computed(() => [{ title: '全部结果', value: 'all' }, ...[...new Set((status.value.history || []).map(historyOutcome))].map(value => ({ title: value, value }))]);
const filteredHistory = computed(() => (status.value.history || []).filter(row => {
  const query = historySearch.value.trim().toLocaleLowerCase();
  return (!query || [row.title, row.rule_name, row.reason, row.rule_summary, row.actual_summary].filter(Boolean).join(' ').toLocaleLowerCase().includes(query))
    && (historyFilter.value === 'all' || historyOutcome(row) === historyFilter.value)
}));
const historyPageCount = computed(() => Math.max(1, Math.ceil(filteredHistory.value.length / historyPageSize.value)));
const pagedHistory = computed(() => filteredHistory.value.slice((historyPage.value - 1) * historyPageSize.value, historyPage.value * historyPageSize.value));
const taskHeaders = [
  { title: '任务', key: 'name', sortable: false, width: '34%' },
  { title: '进度', key: 'progress', sortable: false, width: 140 },
  { title: '状态', key: 'state', sortable: false, width: 120 },
  { title: '分享率', key: 'ratio', sortable: false, width: 110 },
  { title: '速度', key: 'speed', sortable: false, width: 140 },
  { title: '免费截止', key: 'free_until', sortable: false, width: 180 },
];

function notify(text, kind = 'success') {
  message.value = text;
  messageKind.value = kind;
  messageOpen.value = true;
  if (typeof hostToast?.[kind] === 'function') hostToast[kind](text);
  if (kind === 'error') error.value = text;
}

function replaceDraft(value) {
  replacingDraft = true;
  draft.value = clone(value);
  draftRevision.value += 1;
  replacingDraft = false;
}

function ensureSelectedSite() {
  if (!sites.value.some(site => site.id === selectedSiteId.value)) selectedSiteId.value = sites.value[0]?.id || '';
  if (!selectedSite.value) activeTab.value = 'settings';
}

function historyOutcome(row) {
  return row.outcome || (row.event === 'deleted' ? '删除' : row.event === 'added' ? '下载' : '处理')
}

function siteColor(index) {
  return ['#6d4aff', '#00897b', '#d96c00', '#0277bd', '#c62828', '#6d4c41'][index % 6]
}

async function loadStatus(_preserveDraft = true, refreshTasks = true) {
  const scope = selectedSiteId.value;
  const ticket = statusGate.begin(scope);
  const revision = draftRevision.value;
  const epoch = configEpoch;
  const wasDirty = dirty.value;
  const wasSaving = saving.value;
  const includeDownloaders = activeTab.value === 'settings';
  loading.value = true;
  let accepted = false;
  try {
    const query = new URLSearchParams({ include_tasks: 'false', include_downloaders: String(includeDownloaders) });
    if (scope) query.set('site_id', scope);
    const next = unwrap(await props.api.get(`${pluginBase}/status?${query}`));
    if (disposed || !statusGate.current(ticket, selectedSiteId.value)) return false
    if (!next?.settings || !Array.isArray(next.settings.sites)) throw new Error('配置响应不完整，已禁止保存，请重试加载')
    const previousJobs = jobs.value;
    status.value = {
      ...status.value, ...next,
      history: scope && savedSettings.value.sites?.some(site => site.id === scope) ? (next.history || []).filter(row => !row.site_id || row.site_id === scope) : [],
      tasks: status.value.tasks || [],
      downloader_error: status.value.downloader_error,
      downloaders: includeDownloaders ? (next.downloaders || []) : status.value.downloaders,
    };
    if (epoch === configEpoch && !wasSaving && !saving.value) {
      savedSettings.value = clone(next.settings);
      if (!settingsLoaded.value || (!wasDirty && revision === draftRevision.value)) replaceDraft(next.settings);
      settingsLoaded.value = true;
    }
    statusError.value = '';
    lastSynced.value = new Date().toISOString();
    pollFailures = 0;
    const result = reconcileJobs(pendingJobs.value, jobs.value, Date.now());
    pendingJobs.value = result.pending;
    for (const operation of result.finished) notify(`${operationNames[operation]}已结束，请查看处理记录确认结果`);
    for (const operation of result.unconfirmed) notify(`${operationNames[operation]}已提交，但未观测到运行记录；可能已快速结束或仍在排队，请查看记录确认`, 'warning');
    if (result.finished.length || result.unconfirmed.length || Object.keys(previousJobs).some(operation => !jobs.value[operation])) {
      if (activeTab.value === 'tasks') loadTasks(true);
    }
    accepted = true;
    ensureSelectedSite();
  } catch (err) {
    if (!disposed && statusGate.current(ticket, selectedSiteId.value)) {
      statusError.value = err?.message || '加载刷流追新失败';
      pollFailures += 1;
    }
  } finally {
    if (!disposed && statusGate.current(ticket, selectedSiteId.value)) {
      loading.value = false;
      syncPolling();
    }
  }
  if (accepted && refreshTasks && activeTab.value === 'tasks' && scope === selectedSiteId.value) loadTasks();
  return accepted
}

async function loadTasks(force = false) {
  const siteId = selectedSiteId.value;
  if (!siteId || !savedSite.value) {
    status.value.tasks = [];
    return
  }
  const ticket = tasksGate.begin(siteId);
  tasksLoading.value = true;
  try {
    const query = new URLSearchParams({ site_id: siteId, force: String(force) });
    const data = unwrap(await props.api.get(`${pluginBase}/tasks?${query}`));
    if (disposed || !tasksGate.current(ticket, selectedSiteId.value)) return
    status.value = { ...status.value, tasks: data.tasks || [], sites: data.sites || status.value.sites, downloader_error: data.downloader_error || null };
    lastTaskPoll = Date.now();
  } catch (err) {
    if (!disposed && tasksGate.current(ticket, selectedSiteId.value)) status.value.downloader_error = err?.message || '读取 qBittorrent 任务失败';
  } finally {
    if (!disposed && tasksGate.current(ticket, selectedSiteId.value)) tasksLoading.value = false;
  }
}

function refreshPage() {
  pollDeadline = 0;
  pollWarning.value = '';
  loadStatus(true, false);
  if (activeTab.value === 'tasks') loadTasks(true);
}

function selectSite(siteId) {
  selectedSiteId.value = siteId || '';
}

function addSite() {
  if (!settingsLoaded.value) return
  const id = uid();
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
  });
  selectedSiteId.value = id;
  activeTab.value = 'rss';
}

function confirmDeleteSite() {
  const index = sites.value.findIndex(site => site.id === selectedSiteId.value);
  if (index >= 0) sites.value.splice(index, 1);
  selectedSiteId.value = sites.value[Math.min(index, sites.value.length - 1)]?.id || '';
  deleteSiteDialog.value = false;
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
  });
}

function openAuthPage(rule) {
  authRuleId.value = rule.id;
}

function addCleanupRule() {
  selectedSite.value.cleanup_rules.push({
    id: uid(), name: `删种规则 ${selectedSite.value.cleanup_rules.length + 1}`, enabled: taskNameOptions.value.length > 0,
    labels: [...taskNameOptions.value], min_seed_hours: 0, min_ratio: 0, delete_files: false,
  });
}

function updateTaskName(task, value) {
  const previous = task.name;
  task.name = value;
  selectedSite.value.cleanup_rules.forEach(rule => {
    rule.labels = (rule.labels || []).map(label => label === previous ? value : label);
  });
}

function removeRssRule(index) {
  const affected = removeRssAndDisableReferences(selectedSite.value, index);
  if (affected.length) referenceWarning.value = `已自动停用关联删种规则：${affected.join('、')}。请重新选择适用任务，确认后再启用。`;
}

function updateCleanupLabels(rule, labels) {
  rule.labels = labels || [];
  if (!rule.labels.length) rule.enabled = false;
}

function removeRule(collection, index) {
  collection.splice(index, 1);
}

function moveRule(collection, index, offset) {
  const target = index + offset;
  if (target < 0 || target >= collection.length) return
  const [rule] = collection.splice(index, 1);
  collection.splice(target, 0, rule);
}

async function saveSettings() {
  if (!canSave.value) return
  const problem = validateSettings(draft.value);
  if (problem) {
    if (problem.siteId) selectedSiteId.value = problem.siteId;
    activeTab.value = problem.tab || 'settings';
    notify(problem.message, 'error');
    await nextTick();
    await settingsForm.value?.validate();
    return
  }
  const payload = prepareSettings(draft.value);
  const sentRevision = draftRevision.value;
  saving.value = true;
  error.value = '';
  configEpoch += 1;
  statusGate.invalidate();
  loading.value = false;
  try {
    const data = unwrap(await props.api.post(`${pluginBase}/settings`, payload));
    if (disposed) return
    const resolved = saveResolution(draft.value, draftRevision.value, sentRevision, data?.settings, payload);
    savedSettings.value = resolved.saved;
    status.value.settings = clone(resolved.saved);
    status.value.config_pending = Boolean(data?.config_pending);
    if (draftRevision.value === sentRevision) replaceDraft(resolved.draft);
    settingsLoaded.value = true;
    statusError.value = '';
    ensureSelectedSite();
    notify(dirty.value ? '提交的版本已保存；保存期间的新修改仍留在草稿，请再次保存' : data?.config_pending ? '配置已保存，当前后台任务结束后自动生效' : '配置已保存，定时任务已更新');
    // Some hosts reload/close their plugin modal on action. Do not let that
    // discard edits made after this save request was sent.
    if (!dirty.value) emit('action');
  } catch (err) {
    if (disposed) return
    const details = err?.response?.data?.detail || err?.detail;
    const detailText = Array.isArray(details) ? details.map(item => `${(item.loc || []).join('.')}：${item.msg || '字段无效'}`).join('；') : '';
    notify(detailText || err?.message || '保存配置失败，草稿已保留', 'error');
  } finally {
    if (!disposed) {
      configEpoch += 1;
      saving.value = false;
      // The save response is global (its history may be for the first site).
      // Never merge it into this site's views; re-fetch using the current scope.
      loadStatus(true, false);
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
  };
  cleanupDialog.value = true;
}

async function confirmCleanup() {
  const target = cleanupTarget.value;
  cleanupDialog.value = false;
  if (!target || target.siteId !== selectedSiteId.value || target.revision !== fingerprint(savedSettings.value) || runDisabledReason.value) {
    notify('站点或配置已变化，请重新确认执行删种', 'warning');
    return
  }
  await runOperation('cleanup');
}

async function runOperation(operation) {
  if (runDisabledReason.value) { notify(runDisabledReason.value, 'warning'); return }
  if (operationBusy(operation)) return
  const siteId = savedSite.value.id;
  runSubmitting.value = { ...runSubmitting.value, [operation]: true };
  try {
    unwrap(await props.api.post(`${pluginBase}/run`, { operation, site_id: siteId }));
    if (disposed) return
    pendingJobs.value = { ...pendingJobs.value, [operation]: { site_id: siteId, submitted_at: Date.now(), observed: false } };
    pollDeadline = 0;
    pollWarning.value = '';
    notify(`${operationNames[operation]}已使用已保存配置提交到后台`);
    await loadStatus(true, false);
  } catch (err) {
    if (!disposed) notify(err?.message || '提交任务失败', 'error');
  } finally {
    if (!disposed) {
      runSubmitting.value = { ...runSubmitting.value, [operation]: false };
      syncPolling();
    }
  }
}

function stopPolling() {
  if (pollTimer !== null) globalThis.clearTimeout(pollTimer);
  pollTimer = null;
}

function syncPolling() {
  const hasJobs = jobRows.value.length > 0;
  if (disposed || !mounted || globalThis.document?.hidden || !hasJobs) {
    stopPolling();
    if (!hasJobs) { pollDeadline = 0; pollWarning.value = ''; }
    return
  }
  if (!pollDeadline) pollDeadline = Date.now() + POLL_BUDGET;
  if (Date.now() >= pollDeadline) {
    stopPolling();
    pollWarning.value = '自动追踪已达到 15 分钟预算，后台任务不会被取消。点击刷新可继续追踪。';
    return
  }
  if (pollTimer !== null) return
  pollTimer = globalThis.setTimeout(async () => {
    pollTimer = null;
    if (disposed || globalThis.document?.hidden) return
    await loadStatus(true, false);
    if (!disposed && !globalThis.document?.hidden && activeTab.value === 'tasks' && !tasksLoading.value && Date.now() - lastTaskPoll >= 8000) loadTasks(true);
    syncPolling();
  }, Math.min(10000, 2000 * (1 + pollFailures)));
}

async function testDownloader() {
  if (testing.value || !settingsLoaded.value) return
  testing.value = true;
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
    }));
    if (!disposed) notify(`连接正常，当前 ${data.torrent_count} 个任务（测试使用当前草稿，不会保存）`);
  } catch (err) {
    if (!disposed) notify(err?.message || 'qBittorrent 连接失败', 'error');
  } finally {
    if (!disposed) testing.value = false;
  }
}

function historyMeta(row) {
  const parts = [row.outcome || (row.event === 'added' ? '下载' : row.event === 'deleted' ? '删除' : '处理')];
  if (row.reason) parts.push(row.reason);
  else parts.push(row.rule_name || 'RSS 任务', row.resolution || '未知画质');
  if (Number(row.size || 0) > 0) parts.push(formatBytes(row.size));
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
  replaceDraft(savedSettings.value);
  discardDialog.value = false;
  referenceWarning.value = '';
  ensureSelectedSite();
}
function requestClose() {
  if (dirty.value || saving.value) leaveDialog.value = true;
  else emit('close');
}
function beforeUnload(event) {
  if (!dirty.value && !saving.value) return
  event.preventDefault();
  event.returnValue = '';
}
function visibilityChanged() {
  if (clockTimer !== null) globalThis.clearInterval(clockTimer);
  clockTimer = null;
  if (globalThis.document?.hidden) { stopPolling(); return }
  now.value = Date.now();
  clockTimer = globalThis.setInterval(() => { now.value = Date.now(); }, 30000);
  if (mounted) { pollDeadline = 0; loadStatus(true, false); }
}

watch(draft, () => { if (!replacingDraft) draftRevision.value += 1; }, { deep: true, flush: 'sync' });
watch(() => props.initialTab, value => { if (value) activeTab.value = value; });
watch(selectedSiteId, () => {
  statusGate.invalidate();
  tasksGate.invalidate();
  loading.value = false;
  tasksLoading.value = false;
  status.value = { ...status.value, tasks: [], history: [], downloader_error: null };
  authRuleId.value = null;
  cleanupDialog.value = false;
  deleteSiteDialog.value = false;
  taskPage.value = 1;
  historyPage.value = 1;
  taskRuleFilter.value = null;
  historyFilter.value = 'all';
  if (mounted) loadStatus(true);
}, { flush: 'sync' });
watch(activeTab, value => {
  if (!mounted) return
  if (value === 'tasks') loadTasks();
  if (value === 'settings') loadStatus(true, false);
});
watch([taskSearch, taskStateFilter, taskRuleFilter, taskPageSize], () => { taskPage.value = 1; });
watch([historySearch, historyFilter, historyPageSize], () => { historyPage.value = 1; });
watch(taskPageCount, count => { taskPage.value = Math.min(taskPage.value, count); });
watch(historyPageCount, count => { historyPage.value = Math.min(historyPage.value, count); });
onMounted(() => {
  mounted = true;
  globalThis.addEventListener?.('beforeunload', beforeUnload);
  globalThis.document?.addEventListener('visibilitychange', visibilityChanged);
  visibilityChanged();
  // Embedded/hidden WebViews still need their initial configuration; only
  // periodic polling waits for visibility.
  if (globalThis.document?.hidden) loadStatus(true);
});
onBeforeUnmount(() => {
  disposed = true;
  mounted = false;
  stopPolling();
  if (clockTimer !== null) globalThis.clearInterval(clockTimer);
  statusGate.invalidate();
  tasksGate.invalidate();
  globalThis.removeEventListener?.('beforeunload', beforeUnload);
  globalThis.document?.removeEventListener('visibilitychange', visibilityChanged);
});

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VTooltip = _resolveComponent("VTooltip");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VProgressCircular = _resolveComponent("VProgressCircular");
  const _component_VSkeletonLoader = _resolveComponent("VSkeletonLoader");
  const _component_VSheet = _resolveComponent("VSheet");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VTab = _resolveComponent("VTab");
  const _component_VTabs = _resolveComponent("VTabs");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VDataTable = _resolveComponent("VDataTable");
  const _component_VPagination = _resolveComponent("VPagination");
  const _component_VWindowItem = _resolveComponent("VWindowItem");
  const _component_VExpansionPanelTitle = _resolveComponent("VExpansionPanelTitle");
  const _component_VCombobox = _resolveComponent("VCombobox");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VExpansionPanelText = _resolveComponent("VExpansionPanelText");
  const _component_VExpansionPanel = _resolveComponent("VExpansionPanel");
  const _component_VExpansionPanels = _resolveComponent("VExpansionPanels");
  const _component_VWindow = _resolveComponent("VWindow");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VDialog = _resolveComponent("VDialog");
  const _component_VSnackbar = _resolveComponent("VSnackbar");
  const _component_VForm = _resolveComponent("VForm");

  return (_openBlock(), _createBlock(_component_VForm, {
    ref_key: "settingsForm",
    ref: settingsForm,
    class: _normalizeClass(["tracker", { 'tracker--compact': __props.compact }]),
    disabled: !settingsLoaded.value,
    onSubmit: _withModifiers(saveSettings, ["prevent"])
  }, {
    default: _withCtx(() => [
      _createElementVNode("header", _hoisted_1, [
        _createElementVNode("div", _hoisted_2, [
          _createVNode(_component_VIcon, {
            icon: "mdi-rss-box",
            color: "primary",
            size: "30"
          }),
          _cache[65] || (_cache[65] = _createElementVNode("div", null, [
            _createElementVNode("h1", null, "刷流追新"),
            _createElementVNode("p", null, "一个 qBittorrent，统一托管多站点任务")
          ], -1))
        ]),
        _createElementVNode("div", _hoisted_3, [
          _createVNode(_component_VTooltip, { text: "刷新数据" }, {
            activator: _withCtx(({ props: tip }) => [
              _createVNode(_component_VBtn, _mergeProps(tip, {
                icon: "mdi-refresh",
                variant: "text",
                loading: loading.value || tasksLoading.value,
                onClick: refreshPage
              }), null, 16, ["loading"])
            ]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            variant: "text",
            class: "global-settings-button",
            "aria-label": "全局设置",
            onClick: _cache[0] || (_cache[0] = $event => (activeTab.value = 'settings'))
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VIcon, { icon: "mdi-tune-variant" }),
              _cache[66] || (_cache[66] = _createElementVNode("span", { class: "global-settings-label" }, "全局设置", -1))
            ]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            color: "primary",
            variant: "flat",
            "prepend-icon": "mdi-content-save",
            loading: saving.value,
            disabled: !canSave.value,
            onClick: saveSettings
          }, {
            default: _withCtx(() => [...(_cache[67] || (_cache[67] = [
              _createTextVNode("保存", -1)
            ]))]),
            _: 1
          }, 8, ["loading", "disabled"]),
          (__props.showClose)
            ? (_openBlock(), _createBlock(_component_VTooltip, {
                key: 0,
                text: "关闭"
              }, {
                activator: _withCtx(({ props: tip }) => [
                  _createVNode(_component_VBtn, _mergeProps(tip, {
                    icon: "mdi-close",
                    variant: "text",
                    onClick: requestClose
                  }), null, 16)
                ]),
                _: 1
              }))
            : _createCommentVNode("", true)
        ])
      ]),
      (statusError.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: "error",
            variant: "tonal"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(statusError.value) + "。保存与手动运行已禁用。", 1),
              _createVNode(_component_VBtn, {
                size: "small",
                variant: "text",
                loading: loading.value,
                onClick: refreshPage
              }, {
                default: _withCtx(() => [...(_cache[68] || (_cache[68] = [
                  _createTextVNode("重试加载", -1)
                ]))]),
                _: 1
              }, 8, ["loading"])
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (error.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 1,
            type: "error",
            variant: "tonal",
            closable: "",
            "onClick:close": _cache[1] || (_cache[1] = $event => (error.value = ''))
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(error.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (status.value.downloader_error)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 2,
            type: "warning",
            variant: "tonal"
          }, {
            default: _withCtx(() => [
              _createTextVNode("下载器读取失败：" + _toDisplayString(status.value.downloader_error), 1),
              (status.value.tasks.length)
                ? (_openBlock(), _createElementBlock("span", _hoisted_4, "（以下保留最近一次快照）"))
                : _createCommentVNode("", true)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (status.value.config_pending)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 3,
            type: "info",
            variant: "tonal"
          }, {
            default: _withCtx(() => [...(_cache[69] || (_cache[69] = [
              _createTextVNode("新配置已保存，当前后台任务仍使用原配置；本轮结束后自动应用。", -1)
            ]))]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (status.value.state_save_pending)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 4,
            type: "warning",
            variant: "tonal"
          }, {
            default: _withCtx(() => [...(_cache[70] || (_cache[70] = [
              _createTextVNode("运行状态尚未完成落盘，后台补写及后续任务会继续重试。", -1)
            ]))]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (referenceWarning.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 5,
            type: "warning",
            variant: "tonal",
            closable: "",
            "onClick:close": _cache[2] || (_cache[2] = $event => (referenceWarning.value = ''))
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(referenceWarning.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (pollWarning.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 6,
            type: "warning",
            variant: "tonal"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(pollWarning.value), 1),
              _createVNode(_component_VBtn, {
                variant: "text",
                onClick: refreshPage
              }, {
                default: _withCtx(() => [...(_cache[71] || (_cache[71] = [
                  _createTextVNode("继续追踪", -1)
                ]))]),
                _: 1
              })
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (jobRows.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(jobRows.value, (job) => {
              return (_openBlock(), _createElementBlock("div", {
                key: job.operation
              }, [
                _createVNode(_component_VProgressCircular, {
                  indeterminate: "",
                  size: "16",
                  width: "2"
                }),
                _createElementVNode("span", null, _toDisplayString(job.name) + " · " + _toDisplayString(job.siteName) + " · " + _toDisplayString(job.pending ? '已提交，等待后台状态' : `运行中 ${job.running_seconds || 0} 秒`), 1)
              ]))
            }), 128))
          ]))
        : _createCommentVNode("", true),
      _createElementVNode("div", _hoisted_6, _toDisplayString(dirty.value ? '有未保存修改' : settingsLoaded.value ? '当前配置已保存' : '等待加载配置') + " · 最近同步 " + _toDisplayString(_unref(formatTime)(lastSynced.value)), 1),
      (loading.value && !settingsLoaded.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_7, [
            _createVNode(_component_VSkeletonLoader, { type: "list-item-three-line, article" })
          ]))
        : (_openBlock(), _createElementBlock("div", _hoisted_8, [
            _createVNode(_component_VSheet, {
              tag: "aside",
              class: "site-rail app-surface-static"
            }, {
              default: _withCtx(() => [
                _cache[74] || (_cache[74] = _createElementVNode("div", { class: "site-rail__head" }, [
                  _createElementVNode("strong", null, "站点")
                ], -1)),
                _createElementVNode("div", _hoisted_9, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sites.value, (site, index) => {
                    return (_openBlock(), _createElementBlock("button", {
                      key: site.id,
                      type: "button",
                      class: _normalizeClass(["site-item", { 'site-item--active': site.id === selectedSiteId.value }]),
                      style: _normalizeStyle({ '--site-color': siteColor(index) }),
                      onClick: $event => (selectSite(site.id))
                    }, [
                      _createElementVNode("span", null, [
                        _createElementVNode("i", {
                          class: _normalizeClass({ online: site.enabled })
                        }, null, 2),
                        _createTextVNode(_toDisplayString(site.name || '未命名站点'), 1)
                      ]),
                      _createElementVNode("small", null, _toDisplayString(site.rss_rules.length) + " 条 RSS · " + _toDisplayString(site.cleanup_rules.length) + " 条删种", 1)
                    ], 14, _hoisted_10))
                  }), 128)),
                  _createElementVNode("button", {
                    type: "button",
                    class: "site-item site-add",
                    disabled: !settingsLoaded.value,
                    style: {"--site-color":"#6d4aff"},
                    onClick: addSite
                  }, [
                    _createElementVNode("span", null, [
                      _createVNode(_component_VIcon, {
                        icon: "mdi-plus",
                        size: "18"
                      }),
                      _cache[72] || (_cache[72] = _createTextVNode("新增站点", -1))
                    ]),
                    _cache[73] || (_cache[73] = _createElementVNode("small", null, "创建新的站点配置", -1))
                  ], 8, _hoisted_11)
                ])
              ]),
              _: 1
            }),
            _createElementVNode("main", _hoisted_12, [
              _createElementVNode("div", _hoisted_13, [
                _createVNode(_component_VSelect, {
                  "model-value": selectedSiteId.value,
                  items: sites.value,
                  "item-title": "name",
                  "item-value": "id",
                  label: "当前站点",
                  placeholder: "尚未添加站点",
                  "hide-details": "",
                  "onUpdate:modelValue": selectSite
                }, null, 8, ["model-value", "items"]),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "tonal",
                  "prepend-icon": "mdi-plus",
                  disabled: !settingsLoaded.value,
                  onClick: addSite
                }, {
                  default: _withCtx(() => [...(_cache[75] || (_cache[75] = [
                    _createTextVNode("新增", -1)
                  ]))]),
                  _: 1
                }, 8, ["disabled"])
              ]),
              (selectedSite.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
                    _createElementVNode("div", _hoisted_15, [
                      _createVNode(_component_VTextField, {
                        modelValue: selectedSite.value.name,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((selectedSite.value.name) = $event)),
                        label: "站点名称",
                        variant: "outlined",
                        density: "compact",
                        rules: [value => Boolean(String(value || '').trim()) || '站点名称不能为空'],
                        "hide-details": "auto"
                      }, null, 8, ["modelValue", "rules"]),
                      _createVNode(_component_VChip, {
                        color: selectedSite.value.enabled ? 'success' : 'default',
                        size: "small",
                        variant: "tonal"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(selectedSite.value.enabled ? '启用' : '停用'), 1)
                        ]),
                        _: 1
                      }, 8, ["color"])
                    ]),
                    _createElementVNode("div", _hoisted_16, [
                      _createVNode(_component_VSwitch, {
                        modelValue: selectedSite.value.enabled,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((selectedSite.value.enabled) = $event)),
                        label: "启用站点",
                        "hide-details": "",
                        color: "success",
                        inset: ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_VTooltip, { text: "删除站点" }, {
                        activator: _withCtx(({ props: tip }) => [
                          _createVNode(_component_VBtn, _mergeProps(tip, {
                            icon: "mdi-delete-outline",
                            color: "error",
                            variant: "text",
                            onClick: _cache[5] || (_cache[5] = $event => (deleteSiteDialog.value = true))
                          }), null, 16)
                        ]),
                        _: 1
                      })
                    ])
                  ]))
                : _createCommentVNode("", true),
              _createVNode(_component_VTabs, {
                modelValue: activeTab.value,
                "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((activeTab).value = $event)),
                class: "tracker-tabs",
                "show-arrows": ""
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTab, {
                    value: "tasks",
                    "prepend-icon": "mdi-download-network-outline",
                    disabled: !selectedSite.value
                  }, {
                    default: _withCtx(() => [...(_cache[76] || (_cache[76] = [
                      _createTextVNode("任务", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"]),
                  _createVNode(_component_VTab, {
                    value: "rss",
                    "prepend-icon": "mdi-rss",
                    disabled: !selectedSite.value
                  }, {
                    default: _withCtx(() => [...(_cache[77] || (_cache[77] = [
                      _createTextVNode("RSS 任务", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"]),
                  _createVNode(_component_VTab, {
                    value: "cleanup",
                    "prepend-icon": "mdi-broom",
                    disabled: !selectedSite.value
                  }, {
                    default: _withCtx(() => [...(_cache[78] || (_cache[78] = [
                      _createTextVNode("删种规则", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"]),
                  _createVNode(_component_VTab, {
                    value: "history",
                    "prepend-icon": "mdi-history",
                    disabled: !selectedSite.value
                  }, {
                    default: _withCtx(() => [...(_cache[79] || (_cache[79] = [
                      _createTextVNode("记录", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"]),
                  _createVNode(_component_VTab, {
                    value: "site",
                    "prepend-icon": "mdi-shield-key-outline",
                    disabled: !selectedSite.value
                  }, {
                    default: _withCtx(() => [...(_cache[80] || (_cache[80] = [
                      _createTextVNode("站点认证", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"]),
                  _createVNode(_component_VTab, {
                    value: "settings",
                    "prepend-icon": "mdi-tune-variant"
                  }, {
                    default: _withCtx(() => [...(_cache[81] || (_cache[81] = [
                      _createTextVNode("全局设置", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }, 8, ["modelValue"]),
              _createVNode(_component_VWindow, {
                modelValue: activeTab.value,
                "onUpdate:modelValue": _cache[42] || (_cache[42] = $event => ((activeTab).value = $event)),
                class: "tracker-window"
              }, {
                default: _withCtx(() => [
                  (selectedSite.value)
                    ? (_openBlock(), _createBlock(_component_VWindowItem, {
                        key: 0,
                        value: "tasks"
                      }, {
                        default: _withCtx(() => [
                          _createElementVNode("div", _hoisted_17, [
                            _createVNode(_component_VSheet, { class: "stat app-surface-static" }, {
                              default: _withCtx(() => [
                                _cache[82] || (_cache[82] = _createElementVNode("span", null, "托管任务", -1)),
                                _createElementVNode("strong", null, _toDisplayString(selectedSummary.value.managed_count || 0), 1),
                                _createVNode(_component_VIcon, {
                                  icon: "mdi-download-circle-outline",
                                  color: "primary"
                                })
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_VSheet, { class: "stat app-surface-static" }, {
                              default: _withCtx(() => [
                                _cache[83] || (_cache[83] = _createElementVNode("span", null, "RSS 任务", -1)),
                                _createElementVNode("strong", null, _toDisplayString(selectedSite.value.rss_rules.length), 1),
                                _createVNode(_component_VIcon, {
                                  icon: "mdi-rss",
                                  color: "info"
                                })
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_VSheet, { class: "stat app-surface-static" }, {
                              default: _withCtx(() => [
                                _cache[84] || (_cache[84] = _createElementVNode("span", null, "最近读取", -1)),
                                _createElementVNode("strong", null, _toDisplayString(selectedSummary.value.stats?.fetched || 0), 1),
                                _createVNode(_component_VIcon, {
                                  icon: "mdi-text-box-search-outline",
                                  color: "warning"
                                })
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_VSheet, { class: "stat app-surface-static" }, {
                              default: _withCtx(() => [
                                _cache[85] || (_cache[85] = _createElementVNode("span", null, "最近添加", -1)),
                                _createElementVNode("strong", null, _toDisplayString(selectedSummary.value.stats?.added || 0), 1),
                                _createVNode(_component_VIcon, {
                                  icon: "mdi-check-circle-outline",
                                  color: "success"
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _createElementVNode("header", _hoisted_18, [
                                _createElementVNode("div", null, [
                                  _cache[86] || (_cache[86] = _createElementVNode("h2", null, "本插件托管的 qBittorrent 任务", -1)),
                                  _createElementVNode("p", null, _toDisplayString(downloaderLabel.value), 1)
                                ]),
                                _createElementVNode("div", _hoisted_19, [
                                  _createVNode(_component_VBtn, {
                                    variant: "tonal",
                                    "prepend-icon": "mdi-rss",
                                    loading: operationBusy('rss'),
                                    disabled: Boolean(runDisabledReason.value) || operationBusy('rss'),
                                    onClick: _cache[7] || (_cache[7] = $event => (runOperation('rss')))
                                  }, {
                                    default: _withCtx(() => [...(_cache[87] || (_cache[87] = [
                                      _createTextVNode("立即刷新 RSS", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading", "disabled"]),
                                  _createVNode(_component_VBtn, {
                                    color: "error",
                                    variant: "text",
                                    "prepend-icon": "mdi-broom",
                                    loading: operationBusy('cleanup'),
                                    disabled: Boolean(runDisabledReason.value) || operationBusy('cleanup'),
                                    onClick: requestCleanup
                                  }, {
                                    default: _withCtx(() => [...(_cache[88] || (_cache[88] = [
                                      _createTextVNode("执行删种", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading", "disabled"])
                                ])
                              ]),
                              _createElementVNode("p", _hoisted_20, _toDisplayString(runDisabledReason.value || '手动运行使用服务器已保存配置；执行删种可能删除任务及文件。'), 1),
                              _createElementVNode("div", _hoisted_21, [
                                _createVNode(_component_VTextField, {
                                  modelValue: taskSearch.value,
                                  "onUpdate:modelValue": [
                                    _cache[8] || (_cache[8] = $event => ((taskSearch).value = $event)),
                                    _cache[9] || (_cache[9] = $event => (taskSearch.value = $event || ''))
                                  ],
                                  label: "搜索任务名称 / 标签",
                                  "prepend-inner-icon": "mdi-magnify",
                                  clearable: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VSelect, {
                                  modelValue: taskStateFilter.value,
                                  "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((taskStateFilter).value = $event)),
                                  items: stateOptions,
                                  label: "状态",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VSelect, {
                                  modelValue: taskRuleFilter.value,
                                  "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((taskRuleFilter).value = $event)),
                                  items: taskFilterOptions.value,
                                  label: "任务标签",
                                  clearable: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue", "items"])
                              ]),
                              (tasksLoading.value)
                                ? (_openBlock(), _createBlock(_component_VProgressLinear, {
                                    key: 0,
                                    indeterminate: "",
                                    color: "primary",
                                    "aria-label": "正在加载当前站点任务"
                                  }))
                                : _createCommentVNode("", true),
                              (!filteredTasks.value.length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_22, _toDisplayString(tasksLoading.value ? '正在读取当前站点任务…' : status.value.downloader_error ? '下载器离线或读取失败，请重试' : !savedSite.value ? '新站点尚未保存，保存后可读取托管任务' : (status.value.tasks || []).length ? '没有符合搜索 / 筛选条件的任务' : '当前站点没有托管任务'), 1))
                                : (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                                    _createElementVNode("div", _hoisted_23, [
                                      _createVNode(_component_VDataTable, {
                                        headers: taskHeaders,
                                        items: pagedTasks.value,
                                        "items-per-page": -1,
                                        mobile: false,
                                        "hide-default-footer": "",
                                        density: "comfortable",
                                        class: "task-table"
                                      }, {
                                        "item.name": _withCtx(({ item }) => [
                                          _createElementVNode("div", _hoisted_24, [
                                            _createVNode(TaskTitle, {
                                              name: item.name
                                            }, null, 8, ["name"]),
                                            _createElementVNode("small", null, _toDisplayString(_unref(formatBytes)(item.size)) + " · " + _toDisplayString(_unref(taskTags)(item).join(' · ') || '无标签'), 1),
                                            (_unref(pauseExplanation)(item))
                                              ? (_openBlock(), _createElementBlock("small", _hoisted_25, _toDisplayString(_unref(pauseExplanation)(item)), 1))
                                              : _createCommentVNode("", true)
                                          ])
                                        ]),
                                        "item.progress": _withCtx(({ item }) => [
                                          _createElementVNode("div", _hoisted_26, [
                                            _createElementVNode("span", null, _toDisplayString(_unref(taskProgress)(item).toFixed(1)) + "%", 1),
                                            _createVNode(_component_VProgressLinear, {
                                              "model-value": _unref(taskProgress)(item),
                                              height: "6",
                                              rounded: "",
                                              color: "primary"
                                            }, null, 8, ["model-value"])
                                          ])
                                        ]),
                                        "item.state": _withCtx(({ item }) => [
                                          _createVNode(_component_VChip, {
                                            color: _unref(taskState)(item).color,
                                            size: "small",
                                            variant: "tonal"
                                          }, {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(_unref(taskState)(item).title), 1)
                                            ]),
                                            _: 2
                                          }, 1032, ["color"])
                                        ]),
                                        "item.ratio": _withCtx(({ item }) => [
                                          _createTextVNode(_toDisplayString(Number(item.ratio || 0).toFixed(2)), 1),
                                          _createElementVNode("small", _hoisted_27, "做种 " + _toDisplayString(_unref(formatDuration)(item.seeding_time)), 1)
                                        ]),
                                        "item.speed": _withCtx(({ item }) => [
                                          _createElementVNode("span", null, "↓ " + _toDisplayString(_unref(formatBytes)(item.dlspeed)) + "/s", 1),
                                          _createElementVNode("small", _hoisted_28, "↑ " + _toDisplayString(_unref(formatBytes)(item.upspeed)) + "/s", 1)
                                        ]),
                                        "item.free_until": _withCtx(({ item }) => [
                                          _createElementVNode("span", {
                                            class: _normalizeClass({ 'text-warning': _unref(freeRemaining)(item.free_until, now.value).urgent })
                                          }, _toDisplayString(_unref(freeRemaining)(item.free_until, now.value).text), 3),
                                          (item.free_until)
                                            ? (_openBlock(), _createElementBlock("small", _hoisted_29, _toDisplayString(_unref(formatTime)(item.free_until)), 1))
                                            : _createCommentVNode("", true)
                                        ]),
                                        _: 1
                                      }, 8, ["items"])
                                    ]),
                                    _createElementVNode("div", _hoisted_30, [
                                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(pagedTasks.value, (item) => {
                                        return (_openBlock(), _createElementBlock("article", {
                                          key: item.hash || item.name,
                                          class: "task-card"
                                        }, [
                                          _createVNode(TaskTitle, {
                                            name: item.name
                                          }, null, 8, ["name"]),
                                          _createElementVNode("div", _hoisted_31, [
                                            _createVNode(_component_VChip, {
                                              color: _unref(taskState)(item).color,
                                              size: "small",
                                              variant: "tonal"
                                            }, {
                                              default: _withCtx(() => [
                                                _createTextVNode(_toDisplayString(_unref(taskState)(item).title), 1)
                                              ]),
                                              _: 2
                                            }, 1032, ["color"]),
                                            _createElementVNode("span", null, _toDisplayString(_unref(formatBytes)(item.size)), 1),
                                            _createElementVNode("span", null, _toDisplayString(_unref(taskTags)(item).join(' · ') || '无标签'), 1)
                                          ]),
                                          _createElementVNode("div", _hoisted_32, [
                                            _createElementVNode("div", null, [
                                              _cache[89] || (_cache[89] = _createElementVNode("span", null, "下载进度", -1)),
                                              _createElementVNode("strong", null, _toDisplayString(_unref(taskProgress)(item).toFixed(1)) + "%", 1)
                                            ]),
                                            _createVNode(_component_VProgressLinear, {
                                              "model-value": _unref(taskProgress)(item),
                                              height: "7",
                                              rounded: "",
                                              color: "primary"
                                            }, null, 8, ["model-value"])
                                          ]),
                                          _createElementVNode("div", _hoisted_33, [
                                            _createElementVNode("span", null, "↓ " + _toDisplayString(_unref(formatBytes)(item.dlspeed)) + "/s", 1),
                                            _createElementVNode("span", null, "↑ " + _toDisplayString(_unref(formatBytes)(item.upspeed)) + "/s", 1),
                                            _createElementVNode("span", null, "分享率 " + _toDisplayString(Number(item.ratio || 0).toFixed(2)), 1),
                                            _createElementVNode("span", null, "做种 " + _toDisplayString(_unref(formatDuration)(item.seeding_time)), 1)
                                          ]),
                                          _createElementVNode("div", {
                                            class: _normalizeClass(["task-card__deadline", { 'text-warning': _unref(freeRemaining)(item.free_until, now.value).urgent }])
                                          }, [
                                            _createTextVNode(_toDisplayString(_unref(freeRemaining)(item.free_until, now.value).text), 1),
                                            (item.free_until)
                                              ? (_openBlock(), _createElementBlock("small", _hoisted_34, "截止 " + _toDisplayString(_unref(formatTime)(item.free_until)), 1))
                                              : _createCommentVNode("", true)
                                          ], 2),
                                          (_unref(pauseExplanation)(item))
                                            ? (_openBlock(), _createElementBlock("p", _hoisted_35, _toDisplayString(_unref(pauseExplanation)(item)), 1))
                                            : _createCommentVNode("", true)
                                        ]))
                                      }), 128))
                                    ])
                                  ], 64)),
                              _createElementVNode("div", _hoisted_36, [
                                _createElementVNode("span", null, "共 " + _toDisplayString(filteredTasks.value.length) + " 个任务", 1),
                                _createVNode(_component_VSelect, {
                                  modelValue: taskPageSize.value,
                                  "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((taskPageSize).value = $event)),
                                  items: [10, 20, 50],
                                  label: "每页",
                                  "hide-details": "",
                                  density: "compact"
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VPagination, {
                                  modelValue: taskPage.value,
                                  "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((taskPage).value = $event)),
                                  length: taskPageCount.value,
                                  "total-visible": 3,
                                  density: "comfortable",
                                  "aria-label": "任务分页"
                                }, null, 8, ["modelValue", "length"])
                              ])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  (selectedSite.value)
                    ? (_openBlock(), _createBlock(_component_VWindowItem, {
                        key: 1,
                        value: "rss"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _createElementVNode("header", _hoisted_37, [
                                _cache[91] || (_cache[91] = _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "RSS 选种任务"),
                                  _createElementVNode("p", null, "任务名会自动作为 qBittorrent 标签；未选择分辨率时参与最高画质去重")
                                ], -1)),
                                _createVNode(_component_VBtn, {
                                  color: "primary",
                                  variant: "tonal",
                                  "prepend-icon": "mdi-plus",
                                  onClick: addRssRule
                                }, {
                                  default: _withCtx(() => [...(_cache[90] || (_cache[90] = [
                                    _createTextVNode("新增任务", -1)
                                  ]))]),
                                  _: 1
                                })
                              ]),
                              (!selectedSite.value.rss_rules.length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_38, [
                                    _createVNode(_component_VIcon, {
                                      icon: "mdi-rss-off",
                                      size: "46"
                                    }),
                                    _cache[93] || (_cache[93] = _createElementVNode("strong", null, "尚未配置 RSS 任务", -1)),
                                    _createVNode(_component_VBtn, {
                                      variant: "tonal",
                                      onClick: addRssRule
                                    }, {
                                      default: _withCtx(() => [...(_cache[92] || (_cache[92] = [
                                        _createTextVNode("新增任务", -1)
                                      ]))]),
                                      _: 1
                                    })
                                  ]))
                                : (_openBlock(), _createBlock(_component_VExpansionPanels, {
                                    key: 1,
                                    multiple: "",
                                    variant: "accordion",
                                    class: "rule-list"
                                  }, {
                                    default: _withCtx(() => [
                                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selectedSite.value.rss_rules, (rule, index) => {
                                        return (_openBlock(), _createBlock(_component_VExpansionPanel, {
                                          key: rule.id
                                        }, {
                                          default: _withCtx(() => [
                                            _createVNode(_component_VExpansionPanelTitle, null, {
                                              default: _withCtx(() => [
                                                _createElementVNode("div", _hoisted_39, [
                                                  _createVNode(_component_VIcon, {
                                                    icon: "mdi-rss",
                                                    color: "info"
                                                  }),
                                                  _createElementVNode("div", _hoisted_40, [
                                                    _createElementVNode("strong", null, _toDisplayString(rule.name || `RSS 任务 ${index + 1}`), 1),
                                                    _createElementVNode("small", null, _toDisplayString(_unref(ruleSummary)(rule)), 1)
                                                  ]),
                                                  _createVNode(_component_VChip, {
                                                    size: "x-small",
                                                    color: rule.enabled ? 'success' : 'default',
                                                    variant: "tonal"
                                                  }, {
                                                    default: _withCtx(() => [
                                                      _createTextVNode(_toDisplayString(rule.enabled ? '启用' : '停用'), 1)
                                                    ]),
                                                    _: 2
                                                  }, 1032, ["color"])
                                                ])
                                              ]),
                                              _: 2
                                            }, 1024),
                                            _createVNode(_component_VExpansionPanelText, null, {
                                              default: _withCtx(() => [
                                                _createElementVNode("div", _hoisted_41, [
                                                  _createVNode(_component_VTextField, {
                                                    "model-value": rule.name,
                                                    label: "任务名称（同时作为标签）",
                                                    rules: [value => Boolean(String(value || '').trim()) || '任务名称不能为空', value => !String(value || '').includes(',') || '不能包含英文逗号'],
                                                    "hide-details": "auto",
                                                    "onUpdate:modelValue": $event => (updateTaskName(rule, $event))
                                                  }, null, 8, ["model-value", "rules", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VSwitch, {
                                                    modelValue: rule.enabled,
                                                    "onUpdate:modelValue": $event => ((rule.enabled) = $event),
                                                    label: "启用规则",
                                                    "hide-details": "",
                                                    color: "success",
                                                    inset: ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VTextField, {
                                                    modelValue: rule.url,
                                                    "onUpdate:modelValue": $event => ((rule.url) = $event),
                                                    class: "span-2",
                                                    label: "RSS 订阅地址",
                                                    placeholder: "https://tracker.example/torrentrss.php?...",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VCombobox, {
                                                    modelValue: rule.whitelist_keywords,
                                                    "onUpdate:modelValue": $event => ((rule.whitelist_keywords) = $event),
                                                    label: "白名单关键词（必须全部包含）",
                                                    multiple: "",
                                                    chips: "",
                                                    "closable-chips": "",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VCombobox, {
                                                    modelValue: rule.blacklist_keywords,
                                                    "onUpdate:modelValue": $event => ((rule.blacklist_keywords) = $event),
                                                    label: "黑名单关键词（命中任一个即排除）",
                                                    multiple: "",
                                                    chips: "",
                                                    "closable-chips": "",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VSelect, {
                                                    modelValue: rule.resolutions,
                                                    "onUpdate:modelValue": $event => ((rule.resolutions) = $event),
                                                    items: _unref(resolutionOptions),
                                                    label: "分辨率筛选",
                                                    multiple: "",
                                                    chips: "",
                                                    "closable-chips": "",
                                                    clearable: "",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue", "items"]),
                                                  _createVNode(_component_VSelect, {
                                                    modelValue: rule.promotion,
                                                    "onUpdate:modelValue": $event => ((rule.promotion) = $event),
                                                    items: _unref(promotionOptions),
                                                    label: "免费期筛选",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue", "items"]),
                                                  _createElementVNode("div", _hoisted_42, [
                                                    _cache[95] || (_cache[95] = _createElementVNode("span", null, "发种时间范围", -1)),
                                                    _createElementVNode("div", _hoisted_43, [
                                                      _createElementVNode("div", _hoisted_44, [
                                                        _createVNode(_component_VTextField, {
                                                          modelValue: rule.publish_age_from_value,
                                                          "onUpdate:modelValue": $event => ((rule.publish_age_from_value) = $event),
                                                          modelModifiers: { number: true },
                                                          type: "number",
                                                          min: "0",
                                                          label: "从",
                                                          clearable: "",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                        _createVNode(_component_VSelect, {
                                                          modelValue: rule.publish_age_from_unit,
                                                          "onUpdate:modelValue": $event => ((rule.publish_age_from_unit) = $event),
                                                          items: _unref(timeUnitOptions),
                                                          "aria-label": "起始时间单位",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue", "items"])
                                                      ]),
                                                      _cache[94] || (_cache[94] = _createElementVNode("b", null, "至", -1)),
                                                      _createElementVNode("div", _hoisted_45, [
                                                        _createVNode(_component_VTextField, {
                                                          modelValue: rule.publish_age_to_value,
                                                          "onUpdate:modelValue": $event => ((rule.publish_age_to_value) = $event),
                                                          modelModifiers: { number: true },
                                                          type: "number",
                                                          min: "0",
                                                          label: "到",
                                                          clearable: "",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                        _createVNode(_component_VSelect, {
                                                          modelValue: rule.publish_age_to_unit,
                                                          "onUpdate:modelValue": $event => ((rule.publish_age_to_unit) = $event),
                                                          items: _unref(timeUnitOptions),
                                                          "aria-label": "结束时间单位",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue", "items"])
                                                      ])
                                                    ])
                                                  ]),
                                                  _createElementVNode("div", _hoisted_46, [
                                                    _cache[97] || (_cache[97] = _createElementVNode("span", null, "种子大小范围", -1)),
                                                    _createElementVNode("div", _hoisted_47, [
                                                      _createElementVNode("div", _hoisted_48, [
                                                        _createVNode(_component_VTextField, {
                                                          modelValue: rule.size_from_value,
                                                          "onUpdate:modelValue": $event => ((rule.size_from_value) = $event),
                                                          modelModifiers: { number: true },
                                                          type: "number",
                                                          min: "0",
                                                          step: "0.1",
                                                          label: "从",
                                                          clearable: "",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                        _createVNode(_component_VSelect, {
                                                          modelValue: rule.size_from_unit,
                                                          "onUpdate:modelValue": $event => ((rule.size_from_unit) = $event),
                                                          items: _unref(sizeUnitOptions),
                                                          "aria-label": "起始体积单位",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue", "items"])
                                                      ]),
                                                      _cache[96] || (_cache[96] = _createElementVNode("b", null, "至", -1)),
                                                      _createElementVNode("div", _hoisted_49, [
                                                        _createVNode(_component_VTextField, {
                                                          modelValue: rule.size_to_value,
                                                          "onUpdate:modelValue": $event => ((rule.size_to_value) = $event),
                                                          modelModifiers: { number: true },
                                                          type: "number",
                                                          min: "0",
                                                          step: "0.1",
                                                          label: "到",
                                                          clearable: "",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                        _createVNode(_component_VSelect, {
                                                          modelValue: rule.size_to_unit,
                                                          "onUpdate:modelValue": $event => ((rule.size_to_unit) = $event),
                                                          items: _unref(sizeUnitOptions),
                                                          "aria-label": "结束体积单位",
                                                          "hide-details": ""
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue", "items"])
                                                      ])
                                                    ])
                                                  ])
                                                ]),
                                                _createElementVNode("div", _hoisted_50, [
                                                  _createVNode(_component_VTooltip, { text: "上移" }, {
                                                    activator: _withCtx(({ props: tip }) => [
                                                      _createVNode(_component_VBtn, _mergeProps({ ref_for: true }, tip, {
                                                        icon: "mdi-arrow-up",
                                                        size: "small",
                                                        variant: "text",
                                                        disabled: index === 0,
                                                        onClick: $event => (moveRule(selectedSite.value.rss_rules, index, -1))
                                                      }), null, 16, ["disabled", "onClick"])
                                                    ]),
                                                    _: 2
                                                  }, 1024),
                                                  _createVNode(_component_VTooltip, { text: "下移" }, {
                                                    activator: _withCtx(({ props: tip }) => [
                                                      _createVNode(_component_VBtn, _mergeProps({ ref_for: true }, tip, {
                                                        icon: "mdi-arrow-down",
                                                        size: "small",
                                                        variant: "text",
                                                        disabled: index === selectedSite.value.rss_rules.length - 1,
                                                        onClick: $event => (moveRule(selectedSite.value.rss_rules, index, 1))
                                                      }), null, 16, ["disabled", "onClick"])
                                                    ]),
                                                    _: 2
                                                  }, 1024),
                                                  _createVNode(_component_VSpacer),
                                                  _createVNode(_component_VBtn, {
                                                    variant: "tonal",
                                                    color: "primary",
                                                    "prepend-icon": "mdi-shield-key-outline",
                                                    onClick: $event => (openAuthPage(rule))
                                                  }, {
                                                    default: _withCtx(() => [...(_cache[98] || (_cache[98] = [
                                                      _createTextVNode("认证/防403", -1)
                                                    ]))]),
                                                    _: 1
                                                  }, 8, ["onClick"]),
                                                  _createVNode(_component_VBtn, {
                                                    color: "error",
                                                    variant: "text",
                                                    "prepend-icon": "mdi-delete-outline",
                                                    onClick: $event => (removeRssRule(index))
                                                  }, {
                                                    default: _withCtx(() => [...(_cache[99] || (_cache[99] = [
                                                      _createTextVNode("删除", -1)
                                                    ]))]),
                                                    _: 1
                                                  }, 8, ["onClick"])
                                                ])
                                              ]),
                                              _: 2
                                            }, 1024)
                                          ]),
                                          _: 2
                                        }, 1024))
                                      }), 128))
                                    ]),
                                    _: 1
                                  }))
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  (selectedSite.value)
                    ? (_openBlock(), _createBlock(_component_VWindowItem, {
                        key: 2,
                        value: "cleanup"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _createElementVNode("header", _hoisted_51, [
                                _cache[101] || (_cache[101] = _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "顺序删种规则"),
                                  _createElementVNode("p", null, "每个任务只执行第一条标签与阈值均命中的规则")
                                ], -1)),
                                _createVNode(_component_VBtn, {
                                  color: "primary",
                                  variant: "tonal",
                                  "prepend-icon": "mdi-plus",
                                  onClick: addCleanupRule
                                }, {
                                  default: _withCtx(() => [...(_cache[100] || (_cache[100] = [
                                    _createTextVNode("新增规则", -1)
                                  ]))]),
                                  _: 1
                                })
                              ]),
                              (!selectedSite.value.cleanup_rules.length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_52, [
                                    _createVNode(_component_VIcon, {
                                      icon: "mdi-broom",
                                      size: "46"
                                    }),
                                    _cache[103] || (_cache[103] = _createElementVNode("strong", null, "尚未配置自动删种", -1)),
                                    _createVNode(_component_VBtn, {
                                      variant: "tonal",
                                      onClick: addCleanupRule
                                    }, {
                                      default: _withCtx(() => [...(_cache[102] || (_cache[102] = [
                                        _createTextVNode("新增规则", -1)
                                      ]))]),
                                      _: 1
                                    })
                                  ]))
                                : (_openBlock(), _createElementBlock("div", _hoisted_53, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selectedSite.value.cleanup_rules, (rule, index) => {
                                      return (_openBlock(), _createBlock(_component_VSheet, {
                                        key: rule.id,
                                        class: "cleanup-rule"
                                      }, {
                                        default: _withCtx(() => [
                                          _createElementVNode("div", _hoisted_54, _toDisplayString(index + 1), 1),
                                          _createElementVNode("div", _hoisted_55, [
                                            _createElementVNode("p", _hoisted_56, _toDisplayString(rule.enabled ? '启用' : '停用') + " · " + _toDisplayString(rule.labels?.join(' / ') || '未选择任务（不执行）') + " · 做种 ≥ " + _toDisplayString(rule.min_seed_hours || 0) + " 小时且分享率 ≥ " + _toDisplayString(rule.min_ratio || 0) + " · " + _toDisplayString(rule.delete_files ? '同时删除文件' : '保留文件'), 1),
                                            (!rule.labels?.length)
                                              ? (_openBlock(), _createBlock(_component_VAlert, {
                                                  key: 0,
                                                  class: "span-2",
                                                  type: "warning",
                                                  variant: "tonal",
                                                  density: "compact"
                                                }, {
                                                  default: _withCtx(() => [...(_cache[104] || (_cache[104] = [
                                                    _createTextVNode("未选择适用任务，规则不会执行。请重新关联后启用。", -1)
                                                  ]))]),
                                                  _: 1
                                                }))
                                              : _createCommentVNode("", true),
                                            _createVNode(_component_VTextField, {
                                              modelValue: rule.name,
                                              "onUpdate:modelValue": $event => ((rule.name) = $event),
                                              label: "规则名称",
                                              "hide-details": ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                            _createVNode(_component_VSelect, {
                                              "model-value": rule.labels,
                                              items: taskNameOptions.value,
                                              label: "适用任务标签（任一匹配）",
                                              multiple: "",
                                              chips: "",
                                              "closable-chips": "",
                                              "hide-details": "",
                                              "onUpdate:modelValue": $event => (updateCleanupLabels(rule, $event))
                                            }, null, 8, ["model-value", "items", "onUpdate:modelValue"]),
                                            _createVNode(_component_VTextField, {
                                              modelValue: rule.min_seed_hours,
                                              "onUpdate:modelValue": $event => ((rule.min_seed_hours) = $event),
                                              modelModifiers: { number: true },
                                              type: "number",
                                              min: "0",
                                              step: "0.5",
                                              label: "满足做种小时数",
                                              suffix: "小时",
                                              "hide-details": ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                            _createVNode(_component_VTextField, {
                                              modelValue: rule.min_ratio,
                                              "onUpdate:modelValue": $event => ((rule.min_ratio) = $event),
                                              modelModifiers: { number: true },
                                              type: "number",
                                              min: "0",
                                              step: "0.1",
                                              label: "满足分享率",
                                              "hide-details": ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                            _createVNode(_component_VSwitch, {
                                              modelValue: rule.enabled,
                                              "onUpdate:modelValue": $event => ((rule.enabled) = $event),
                                              label: "启用",
                                              disabled: !rule.labels?.length,
                                              "hide-details": "",
                                              color: "success",
                                              inset: ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue", "disabled"]),
                                            _createVNode(_component_VSwitch, {
                                              modelValue: rule.delete_files,
                                              "onUpdate:modelValue": $event => ((rule.delete_files) = $event),
                                              label: "同时删除文件",
                                              "hide-details": "",
                                              color: "error",
                                              inset: ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                          ]),
                                          _createElementVNode("div", _hoisted_57, [
                                            _createVNode(_component_VTooltip, { text: "上移" }, {
                                              activator: _withCtx(({ props: tip }) => [
                                                _createVNode(_component_VBtn, _mergeProps({ ref_for: true }, tip, {
                                                  icon: "mdi-arrow-up",
                                                  size: "small",
                                                  variant: "text",
                                                  disabled: index === 0,
                                                  onClick: $event => (moveRule(selectedSite.value.cleanup_rules, index, -1))
                                                }), null, 16, ["disabled", "onClick"])
                                              ]),
                                              _: 2
                                            }, 1024),
                                            _createVNode(_component_VTooltip, { text: "下移" }, {
                                              activator: _withCtx(({ props: tip }) => [
                                                _createVNode(_component_VBtn, _mergeProps({ ref_for: true }, tip, {
                                                  icon: "mdi-arrow-down",
                                                  size: "small",
                                                  variant: "text",
                                                  disabled: index === selectedSite.value.cleanup_rules.length - 1,
                                                  onClick: $event => (moveRule(selectedSite.value.cleanup_rules, index, 1))
                                                }), null, 16, ["disabled", "onClick"])
                                              ]),
                                              _: 2
                                            }, 1024),
                                            _createVNode(_component_VTooltip, { text: "删除" }, {
                                              activator: _withCtx(({ props: tip }) => [
                                                _createVNode(_component_VBtn, _mergeProps({ ref_for: true }, tip, {
                                                  icon: "mdi-delete-outline",
                                                  size: "small",
                                                  color: "error",
                                                  variant: "text",
                                                  onClick: $event => (removeRule(selectedSite.value.cleanup_rules, index))
                                                }), null, 16, ["onClick"])
                                              ]),
                                              _: 2
                                            }, 1024)
                                          ])
                                        ]),
                                        _: 2
                                      }, 1024))
                                    }), 128))
                                  ]))
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  (selectedSite.value)
                    ? (_openBlock(), _createBlock(_component_VWindowItem, {
                        key: 3,
                        value: "history"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _cache[107] || (_cache[107] = _createElementVNode("header", { class: "panel__head" }, [
                                _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "处理记录"),
                                  _createElementVNode("p", null, "对比规则条件与实际检测结果；点击名称进入种子页面")
                                ])
                              ], -1)),
                              _createElementVNode("div", _hoisted_58, [
                                _createVNode(_component_VTextField, {
                                  modelValue: historySearch.value,
                                  "onUpdate:modelValue": [
                                    _cache[14] || (_cache[14] = $event => ((historySearch).value = $event)),
                                    _cache[15] || (_cache[15] = $event => (historySearch.value = $event || ''))
                                  ],
                                  label: "搜索标题 / 任务名称 / 原因",
                                  "prepend-inner-icon": "mdi-magnify",
                                  clearable: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VSelect, {
                                  modelValue: historyFilter.value,
                                  "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((historyFilter).value = $event)),
                                  items: historyOptions.value,
                                  label: "处理结果",
                                  "hide-details": ""
                                }, null, 8, ["modelValue", "items"])
                              ]),
                              (loading.value)
                                ? (_openBlock(), _createBlock(_component_VProgressLinear, {
                                    key: 0,
                                    indeterminate: "",
                                    color: "primary",
                                    "aria-label": "正在加载当前站点记录"
                                  }))
                                : _createCommentVNode("", true),
                              _createElementVNode("div", _hoisted_59, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(pagedHistory.value, (row, index) => {
                                  return (_openBlock(), _createElementBlock("article", {
                                    key: `${row.time}-${row.title}-${row.outcome}-${index}`
                                  }, [
                                    _createVNode(_component_VIcon, {
                                      icon: historyIcon(row),
                                      color: historyColor(row)
                                    }, null, 8, ["icon", "color"]),
                                    _createElementVNode("div", null, [
                                      (row.link)
                                        ? (_openBlock(), _createElementBlock("a", {
                                            key: 0,
                                            href: row.link,
                                            target: "_blank",
                                            rel: "noopener noreferrer"
                                          }, _toDisplayString(row.title), 9, _hoisted_60))
                                        : (_openBlock(), _createElementBlock("strong", _hoisted_61, _toDisplayString(row.title), 1)),
                                      _createElementVNode("span", _hoisted_62, _toDisplayString(historyMeta(row)), 1),
                                      (row.rule_summary)
                                        ? (_openBlock(), _createElementBlock("span", _hoisted_63, [
                                            _cache[105] || (_cache[105] = _createElementVNode("b", null, "规则条件：", -1)),
                                            _createTextVNode(_toDisplayString(row.rule_summary), 1)
                                          ]))
                                        : _createCommentVNode("", true),
                                      (row.actual_summary)
                                        ? (_openBlock(), _createElementBlock("span", _hoisted_64, [
                                            _cache[106] || (_cache[106] = _createElementVNode("b", null, "实际检测：", -1)),
                                            _createTextVNode(_toDisplayString(row.actual_summary), 1)
                                          ]))
                                        : _createCommentVNode("", true)
                                    ]),
                                    _createElementVNode("time", null, _toDisplayString(_unref(formatTime)(row.time)), 1)
                                  ]))
                                }), 128)),
                                (!filteredHistory.value.length)
                                  ? (_openBlock(), _createElementBlock("div", _hoisted_65, _toDisplayString(loading.value ? '正在读取当前站点记录…' : statusError.value ? '记录加载失败，请重试' : status.value.history?.length ? '没有符合搜索 / 筛选条件的记录' : '暂无处理记录'), 1))
                                  : _createCommentVNode("", true)
                              ]),
                              _createElementVNode("div", _hoisted_66, [
                                _createElementVNode("span", null, "已加载 " + _toDisplayString(status.value.history?.length || 0) + " 条 · 符合 " + _toDisplayString(filteredHistory.value.length) + " 条", 1),
                                _createVNode(_component_VSelect, {
                                  modelValue: historyPageSize.value,
                                  "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((historyPageSize).value = $event)),
                                  items: [10, 20, 50],
                                  label: "每页",
                                  "hide-details": "",
                                  density: "compact"
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VPagination, {
                                  modelValue: historyPage.value,
                                  "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((historyPage).value = $event)),
                                  length: historyPageCount.value,
                                  "total-visible": 3,
                                  density: "comfortable",
                                  "aria-label": "记录分页"
                                }, null, 8, ["modelValue", "length"])
                              ]),
                              _cache[108] || (_cache[108] = _createElementVNode("p", { class: "block-muted" }, "分页与搜索基于 status 接口返回的最近记录，不代表全部历史。", -1))
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  (selectedSite.value)
                    ? (_openBlock(), _createBlock(_component_VWindowItem, {
                        key: 4,
                        value: "site"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _cache[109] || (_cache[109] = _createElementVNode("header", { class: "panel__head" }, [
                                _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "站点认证与默认请求设置"),
                                  _createElementVNode("p", null, "仅作用于当前站点；RSS 任务可以单独覆盖这些设置")
                                ])
                              ], -1)),
                              _createElementVNode("div", _hoisted_67, [
                                _createVNode(_component_VSwitch, {
                                  modelValue: selectedSite.value.use_proxy,
                                  "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((selectedSite.value.use_proxy) = $event)),
                                  label: "本站点默认使用代理",
                                  "hide-details": "",
                                  inset: ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: selectedSite.value.user_agent,
                                  "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((selectedSite.value.user_agent) = $event)),
                                  class: "span-2",
                                  label: "站点自定义 User-Agent",
                                  clearable: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: selectedSite.value.uid,
                                  "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((selectedSite.value.uid) = $event)),
                                  label: "站点 UID（可选）",
                                  hint: "自动补到 RSS / 详情地址",
                                  "persistent-hint": "",
                                  "hide-details": "auto"
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: selectedSite.value.passkey,
                                  "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((selectedSite.value.passkey) = $event)),
                                  type: "password",
                                  label: "站点 Passkey（可选）",
                                  hint: "仅在保存后生效",
                                  "persistent-hint": "",
                                  "hide-details": "auto"
                                }, null, 8, ["modelValue"])
                              ])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  _createVNode(_component_VWindowItem, { value: "settings" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                        default: _withCtx(() => [
                          _cache[113] || (_cache[113] = _createElementVNode("header", { class: "panel__head" }, [
                            _createElementVNode("div", null, [
                              _createElementVNode("h2", null, "全局连接与调度"),
                              _createElementVNode("p", null, "所有站点共用这一项 qBittorrent 配置")
                            ])
                          ], -1)),
                          _createElementVNode("div", _hoisted_68, [
                            _createVNode(_component_VSwitch, {
                              modelValue: draft.value.enabled,
                              "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((draft.value.enabled) = $event)),
                              label: "启用插件",
                              color: "success",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VSwitch, {
                              modelValue: draft.value.show_sidebar_nav,
                              "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((draft.value.show_sidebar_nav) = $event)),
                              label: "显示侧栏入口",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VSelect, {
                              modelValue: draft.value.downloader_mode,
                              "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((draft.value.downloader_mode) = $event)),
                              items: [{ title: 'MoviePilot 内置下载器', value: 'moviepilot' }, { title: '自定义 qBittorrent', value: 'custom' }],
                              label: "qBittorrent 连接方式",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            (draft.value.downloader_mode !== 'custom')
                              ? (_openBlock(), _createBlock(_component_VSelect, {
                                  key: 0,
                                  modelValue: draft.value.downloader,
                                  "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((draft.value.downloader) = $event)),
                                  class: "span-2",
                                  items: status.value.downloaders,
                                  label: "MoviePilot qBittorrent 下载器",
                                  placeholder: "选择 MoviePilot 中已配置的 qBittorrent",
                                  "hide-details": ""
                                }, {
                                  append: _withCtx(() => [
                                    _createVNode(_component_VTooltip, { text: "测试连接" }, {
                                      activator: _withCtx(({ props: tip }) => [
                                        _createVNode(_component_VBtn, _mergeProps(tip, {
                                          icon: "mdi-connection",
                                          variant: "text",
                                          loading: testing.value,
                                          disabled: !settingsLoaded.value,
                                          onClick: testDownloader
                                        }), null, 16, ["loading", "disabled"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }, 8, ["modelValue", "items"]))
                              : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                                  _createVNode(_component_VTextField, {
                                    modelValue: draft.value.custom_qb_url,
                                    "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((draft.value.custom_qb_url) = $event)),
                                    label: "qBittorrent WebUI 地址",
                                    placeholder: "http://127.0.0.1:8080",
                                    "hide-details": ""
                                  }, null, 8, ["modelValue"]),
                                  _createVNode(_component_VTextField, {
                                    modelValue: draft.value.custom_qb_username,
                                    "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((draft.value.custom_qb_username) = $event)),
                                    label: "qBittorrent 用户名",
                                    "hide-details": ""
                                  }, null, 8, ["modelValue"]),
                                  _createVNode(_component_VTextField, {
                                    modelValue: draft.value.custom_qb_password,
                                    "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((draft.value.custom_qb_password) = $event)),
                                    type: "password",
                                    label: "qBittorrent 密码",
                                    "hide-details": ""
                                  }, null, 8, ["modelValue"]),
                                  _createVNode(_component_VTextField, {
                                    modelValue: draft.value.custom_qb_save_path,
                                    "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((draft.value.custom_qb_save_path) = $event)),
                                    class: "span-2",
                                    label: "下载保存路径（可选）",
                                    placeholder: "/downloads 或 D:\\\\Downloads",
                                    "hide-details": ""
                                  }, null, 8, ["modelValue"]),
                                  _createVNode(_component_VBtn, {
                                    class: "span-2",
                                    variant: "tonal",
                                    "prepend-icon": "mdi-connection",
                                    loading: testing.value,
                                    disabled: !settingsLoaded.value,
                                    onClick: testDownloader
                                  }, {
                                    default: _withCtx(() => [...(_cache[110] || (_cache[110] = [
                                      _createTextVNode("测试自定义 qBittorrent 连接", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading", "disabled"])
                                ], 64)),
                            _createVNode(_component_VSwitch, {
                              modelValue: draft.value.highest_resolution_dedup,
                              "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((draft.value.highest_resolution_dedup) = $event)),
                              class: "span-2",
                              label: "重复下载只保留最佳版本（已下载完成的内容不会删除）",
                              color: "primary",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VSwitch, {
                              modelValue: draft.value.avoid_dead_seeds,
                              "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((draft.value.avoid_dead_seeds) = $event)),
                              class: "span-2",
                              label: "避开无做种死种并自动切换可下载版本",
                              color: "warning",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.dead_seed_wait_minutes,
                              "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((draft.value.dead_seed_wait_minutes) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "1",
                              label: "死种等待时间",
                              suffix: "分钟",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.dead_seed_min_seeders,
                              "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((draft.value.dead_seed_min_seeders) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "0",
                              label: "最低做种数",
                              suffix: "个",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VSwitch, {
                              modelValue: draft.value.dead_seed_delete_files,
                              "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((draft.value.dead_seed_delete_files) = $event)),
                              label: "死种删除文件",
                              color: "error",
                              "hide-details": "",
                              inset: ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.rss_interval_minutes,
                              "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((draft.value.rss_interval_minutes) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "1",
                              label: "RSS 刷新间隔（分钟）",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.free_monitor_interval_minutes,
                              "onUpdate:modelValue": _cache[37] || (_cache[37] = $event => ((draft.value.free_monitor_interval_minutes) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "1",
                              label: "免费期检查间隔（分钟）",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.cleanup_interval_minutes,
                              "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((draft.value.cleanup_interval_minutes) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "1",
                              label: "自动删种间隔（分钟）",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.request_timeout_seconds,
                              "onUpdate:modelValue": _cache[39] || (_cache[39] = $event => ((draft.value.request_timeout_seconds) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "5",
                              max: "120",
                              label: "RSS 请求超时（秒）",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VTextField, {
                              modelValue: draft.value.history_limit,
                              "onUpdate:modelValue": _cache[40] || (_cache[40] = $event => ((draft.value.history_limit) = $event)),
                              modelModifiers: { number: true },
                              type: "number",
                              min: "50",
                              max: "5000",
                              label: "历史记录上限",
                              "hide-details": ""
                            }, null, 8, ["modelValue"])
                          ]),
                          _createElementVNode("p", _hoisted_69, "连接测试使用当前输入，不会保存；" + _toDisplayString(runDisabledReason.value || '手动检查使用已保存的当前站点配置。'), 1),
                          _createElementVNode("div", _hoisted_70, [
                            _createVNode(_component_VBtn, {
                              color: "primary",
                              variant: "flat",
                              "prepend-icon": "mdi-content-save",
                              loading: saving.value,
                              disabled: !canSave.value,
                              onClick: saveSettings
                            }, {
                              default: _withCtx(() => [...(_cache[111] || (_cache[111] = [
                                _createTextVNode("保存全部设置", -1)
                              ]))]),
                              _: 1
                            }, 8, ["loading", "disabled"]),
                            _createVNode(_component_VBtn, {
                              variant: "tonal",
                              "prepend-icon": "mdi-timer-refresh-outline",
                              loading: operationBusy('free_monitor'),
                              disabled: Boolean(runDisabledReason.value) || operationBusy('free_monitor'),
                              onClick: _cache[41] || (_cache[41] = $event => (runOperation('free_monitor')))
                            }, {
                              default: _withCtx(() => [...(_cache[112] || (_cache[112] = [
                                _createTextVNode("检查免费期", -1)
                              ]))]),
                              _: 1
                            }, 8, ["loading", "disabled"])
                          ])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }, 8, ["modelValue"]),
              (!selectedSite.value && settingsLoaded.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_71, [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-web-off",
                      size: "56"
                    }),
                    _cache[115] || (_cache[115] = _createElementVNode("strong", null, "还没有站点", -1)),
                    _cache[116] || (_cache[116] = _createElementVNode("p", null, "可以先在全局设置配置下载器，再新增站点。", -1)),
                    _createVNode(_component_VBtn, {
                      color: "primary",
                      variant: "flat",
                      "prepend-icon": "mdi-plus",
                      onClick: addSite
                    }, {
                      default: _withCtx(() => [...(_cache[114] || (_cache[114] = [
                        _createTextVNode("创建第一个站点", -1)
                      ]))]),
                      _: 1
                    })
                  ]))
                : _createCommentVNode("", true)
            ])
          ])),
      _createVNode(_component_VDialog, {
        modelValue: authDialog.value,
        "onUpdate:modelValue": _cache[52] || (_cache[52] = $event => ((authDialog).value = $event)),
        "max-width": "52rem",
        scrollable: ""
      }, {
        default: _withCtx(() => [
          (authRule.value)
            ? (_openBlock(), _createBlock(_component_VCard, {
                key: 0,
                title: "任务认证与防 403"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VCardText, null, {
                    default: _withCtx(() => [
                      _cache[118] || (_cache[118] = _createElementVNode("p", { class: "block-muted auth-help" }, "此页面只作用于当前 RSS 任务。任务级填写优先于站点默认值；留空则继承站点设置或 MoviePilot 站点 Cookie。", -1)),
                      _createElementVNode("div", _hoisted_72, [
                        _createVNode(_component_VTextField, {
                          modelValue: authRule.value.uid,
                          "onUpdate:modelValue": _cache[43] || (_cache[43] = $event => ((authRule.value.uid) = $event)),
                          label: "UID",
                          placeholder: "站点用户 UID",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VTextField, {
                          modelValue: authRule.value.passkey,
                          "onUpdate:modelValue": _cache[44] || (_cache[44] = $event => ((authRule.value.passkey) = $event)),
                          label: "Passkey",
                          type: "password",
                          placeholder: "站点 Passkey",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VTextField, {
                          modelValue: authRule.value.rss_key,
                          "onUpdate:modelValue": _cache[45] || (_cache[45] = $event => ((authRule.value.rss_key) = $event)),
                          label: "RSS 密钥",
                          type: "password",
                          placeholder: "站点提供的 RSS Key",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VTextField, {
                          modelValue: authRule.value.rss_key_name,
                          "onUpdate:modelValue": _cache[46] || (_cache[46] = $event => ((authRule.value.rss_key_name) = $event)),
                          label: "RSS 密钥参数名",
                          placeholder: "默认 rsskey，也可能是 authkey",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VTextarea, {
                          modelValue: authRule.value.cookie,
                          "onUpdate:modelValue": _cache[47] || (_cache[47] = $event => ((authRule.value.cookie) = $event)),
                          class: "span-2",
                          label: "Cookie（可选）",
                          placeholder: "从浏览器复制的完整 Cookie，例如 c_secure_uid=...; c_secure_pass=...",
                          rows: "3",
                          "auto-grow": "",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VTextField, {
                          modelValue: authRule.value.user_agent,
                          "onUpdate:modelValue": _cache[48] || (_cache[48] = $event => ((authRule.value.user_agent) = $event)),
                          label: "User-Agent（可选）",
                          placeholder: "留空使用站点/MoviePilot 默认值",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VTextField, {
                          modelValue: authRule.value.referer,
                          "onUpdate:modelValue": _cache[49] || (_cache[49] = $event => ((authRule.value.referer) = $event)),
                          label: "Referer（可选）",
                          placeholder: "https://站点域名/",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VSelect, {
                          "model-value": authRule.value.use_proxy ?? null,
                          items: _unref(proxyOptions),
                          label: "此任务代理策略",
                          hint: "继承站点 / 强制开启 / 强制关闭",
                          "persistent-hint": "",
                          "hide-details": "auto",
                          "onUpdate:modelValue": _cache[50] || (_cache[50] = $event => (authRule.value.use_proxy = $event))
                        }, null, 8, ["model-value", "items"])
                      ]),
                      _createVNode(_component_VAlert, {
                        class: "auth-alert",
                        type: "info",
                        variant: "tonal",
                        density: "compact"
                      }, {
                        default: _withCtx(() => [...(_cache[117] || (_cache[117] = [
                          _createTextVNode("Audiences/NexusPHP 页面只显示“免费”徽章时，建议同时填写 Cookie；UID/Passkey 会自动补到 RSS 和详情地址。", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCardActions, null, {
                    default: _withCtx(() => [
                      _createVNode(_component_VSpacer),
                      _createVNode(_component_VBtn, {
                        variant: "text",
                        onClick: _cache[51] || (_cache[51] = $event => (authRuleId.value = null))
                      }, {
                        default: _withCtx(() => [...(_cache[119] || (_cache[119] = [
                          _createTextVNode("关闭", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }))
            : _createCommentVNode("", true)
        ]),
        _: 1
      }, 8, ["modelValue"]),
      _createVNode(_component_VDialog, {
        modelValue: deleteSiteDialog.value,
        "onUpdate:modelValue": _cache[54] || (_cache[54] = $event => ((deleteSiteDialog).value = $event)),
        "max-width": "28rem"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCard, { title: "删除站点" }, {
            default: _withCtx(() => [
              _createVNode(_component_VCardText, null, {
                default: _withCtx(() => [
                  _createTextVNode("删除“" + _toDisplayString(selectedSite.value?.name) + "”及其所有规则？下载器中的现有任务不会被删除。此修改在保存后生效。", 1)
                ]),
                _: 1
              }),
              _createVNode(_component_VCardActions, null, {
                default: _withCtx(() => [
                  _createVNode(_component_VSpacer),
                  _createVNode(_component_VBtn, {
                    variant: "text",
                    onClick: _cache[53] || (_cache[53] = $event => (deleteSiteDialog.value = false))
                  }, {
                    default: _withCtx(() => [...(_cache[120] || (_cache[120] = [
                      _createTextVNode("取消", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    color: "error",
                    variant: "flat",
                    onClick: confirmDeleteSite
                  }, {
                    default: _withCtx(() => [...(_cache[121] || (_cache[121] = [
                      _createTextVNode("删除", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["modelValue"]),
      _createVNode(_component_VDialog, {
        modelValue: cleanupDialog.value,
        "onUpdate:modelValue": _cache[56] || (_cache[56] = $event => ((cleanupDialog).value = $event)),
        "max-width": "30rem"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCard, { title: "确认执行删种" }, {
            default: _withCtx(() => [
              _createVNode(_component_VCardText, null, {
                default: _withCtx(() => [
                  _createElementVNode("p", null, [
                    _cache[122] || (_cache[122] = _createTextVNode("作用站点：", -1)),
                    _createElementVNode("strong", null, _toDisplayString(cleanupTarget.value?.name), 1)
                  ]),
                  _cache[123] || (_cache[123] = _createElementVNode("p", null, "将使用服务器已保存的删种规则，立即删除符合条件的托管任务。这不是只读预览。", -1)),
                  _createVNode(_component_VAlert, {
                    type: cleanupTarget.value?.deleteFiles ? 'error' : 'warning',
                    variant: "tonal"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(cleanupTarget.value?.deleteFiles ? '启用规则包含「同时删除文件」，符合条件的数据文件也会被删除，无法撤销。' : '当前启用的删种规则保留文件，只从下载器移除符合条件的任务。'), 1)
                    ]),
                    _: 1
                  }, 8, ["type"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCardActions, null, {
                default: _withCtx(() => [
                  _createVNode(_component_VSpacer),
                  _createVNode(_component_VBtn, {
                    onClick: _cache[55] || (_cache[55] = $event => (cleanupDialog.value = false))
                  }, {
                    default: _withCtx(() => [...(_cache[124] || (_cache[124] = [
                      _createTextVNode("取消", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    color: "error",
                    variant: "flat",
                    disabled: Boolean(runDisabledReason.value) || operationBusy('cleanup'),
                    onClick: confirmCleanup
                  }, {
                    default: _withCtx(() => [...(_cache[125] || (_cache[125] = [
                      _createTextVNode("确认执行删种", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["modelValue"]),
      _createVNode(_component_VDialog, {
        modelValue: discardDialog.value,
        "onUpdate:modelValue": _cache[58] || (_cache[58] = $event => ((discardDialog).value = $event)),
        "max-width": "28rem"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCard, { title: "放弃未保存修改？" }, {
            default: _withCtx(() => [
              _createVNode(_component_VCardText, null, {
                default: _withCtx(() => [...(_cache[126] || (_cache[126] = [
                  _createTextVNode("所有站点的本地草稿将恢复为最近一次已保存配置。", -1)
                ]))]),
                _: 1
              }),
              _createVNode(_component_VCardActions, null, {
                default: _withCtx(() => [
                  _createVNode(_component_VSpacer),
                  _createVNode(_component_VBtn, {
                    onClick: _cache[57] || (_cache[57] = $event => (discardDialog.value = false))
                  }, {
                    default: _withCtx(() => [...(_cache[127] || (_cache[127] = [
                      _createTextVNode("继续编辑", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    color: "warning",
                    disabled: saving.value,
                    onClick: discardChanges
                  }, {
                    default: _withCtx(() => [...(_cache[128] || (_cache[128] = [
                      _createTextVNode("放弃修改", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["modelValue"]),
      _createVNode(_component_VDialog, {
        modelValue: leaveDialog.value,
        "onUpdate:modelValue": _cache[61] || (_cache[61] = $event => ((leaveDialog).value = $event)),
        "max-width": "28rem"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCard, { title: "尚有未保存修改" }, {
            default: _withCtx(() => [
              _createVNode(_component_VCardText, null, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(saving.value ? '保存仍在提交中，建议等待结果后再关闭。' : '关闭会丢失未保存的草稿，确定离开？'), 1)
                ]),
                _: 1
              }),
              _createVNode(_component_VCardActions, null, {
                default: _withCtx(() => [
                  _createVNode(_component_VSpacer),
                  _createVNode(_component_VBtn, {
                    onClick: _cache[59] || (_cache[59] = $event => (leaveDialog.value = false))
                  }, {
                    default: _withCtx(() => [...(_cache[129] || (_cache[129] = [
                      _createTextVNode("继续编辑", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    color: "warning",
                    onClick: _cache[60] || (_cache[60] = $event => (_ctx.$emit('close')))
                  }, {
                    default: _withCtx(() => [...(_cache[130] || (_cache[130] = [
                      _createTextVNode("仍然关闭", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["modelValue"]),
      (dirty.value || saving.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_73, [
            _createElementVNode("span", null, _toDisplayString(saving.value ? '正在保存提交的版本；可以继续编辑' : '有未保存修改 · 手动运行暂不可用'), 1),
            _createElementVNode("div", null, [
              _createVNode(_component_VBtn, {
                variant: "text",
                disabled: saving.value,
                onClick: _cache[62] || (_cache[62] = $event => (discardDialog.value = true))
              }, {
                default: _withCtx(() => [...(_cache[131] || (_cache[131] = [
                  _createTextVNode("放弃", -1)
                ]))]),
                _: 1
              }, 8, ["disabled"]),
              _createVNode(_component_VBtn, {
                color: "primary",
                variant: "flat",
                loading: saving.value,
                disabled: !canSave.value,
                onClick: saveSettings
              }, {
                default: _withCtx(() => [...(_cache[132] || (_cache[132] = [
                  _createTextVNode("保存全部修改", -1)
                ]))]),
                _: 1
              }, 8, ["loading", "disabled"])
            ])
          ]))
        : _createCommentVNode("", true),
      _createVNode(_component_VSnackbar, {
        modelValue: messageOpen.value,
        "onUpdate:modelValue": _cache[64] || (_cache[64] = $event => ((messageOpen).value = $event)),
        color: messageKind.value,
        timeout: 6000
      }, {
        actions: _withCtx(() => [
          _createVNode(_component_VBtn, {
            variant: "text",
            onClick: _cache[63] || (_cache[63] = $event => (messageOpen.value = false))
          }, {
            default: _withCtx(() => [...(_cache[133] || (_cache[133] = [
              _createTextVNode("关闭", -1)
            ]))]),
            _: 1
          })
        ]),
        default: _withCtx(() => [
          _createTextVNode(_toDisplayString(message.value), 1)
        ]),
        _: 1
      }, 8, ["modelValue", "color"])
    ]),
    _: 1
  }, 8, ["disabled", "class"]))
}
}

};
const Workbench = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c7b6b543"]]);

export { Workbench as W };
