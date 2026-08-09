import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,mergeProps:_mergeProps,withCtx:_withCtx,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle} = await importShared('vue');


const _hoisted_1 = { class: "tracker__header" };
const _hoisted_2 = { class: "tracker__identity" };
const _hoisted_3 = { class: "tracker__actions" };
const _hoisted_4 = {
  key: 2,
  class: "tracker__loading"
};
const _hoisted_5 = {
  key: 3,
  class: "tracker__layout"
};
const _hoisted_6 = { class: "site-list" };
const _hoisted_7 = ["onClick"];
const _hoisted_8 = { class: "workspace" };
const _hoisted_9 = { class: "site-head" };
const _hoisted_10 = { class: "site-head__name" };
const _hoisted_11 = { class: "site-head__actions" };
const _hoisted_12 = { class: "stats" };
const _hoisted_13 = { class: "panel__head" };
const _hoisted_14 = { class: "task-name" };
const _hoisted_15 = { class: "progress-cell" };
const _hoisted_16 = { class: "block-muted" };
const _hoisted_17 = { class: "block-muted" };
const _hoisted_18 = { class: "panel__head" };
const _hoisted_19 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_20 = { class: "rule-title" };
const _hoisted_21 = { class: "rule-grid" };
const _hoisted_22 = { class: "range-control" };
const _hoisted_23 = { class: "range-fields" };
const _hoisted_24 = { class: "range-control" };
const _hoisted_25 = { class: "range-fields" };
const _hoisted_26 = { class: "rule-actions" };
const _hoisted_27 = { class: "panel__head" };
const _hoisted_28 = {
  key: 0,
  class: "empty-state"
};
const _hoisted_29 = {
  key: 1,
  class: "cleanup-list"
};
const _hoisted_30 = { class: "order" };
const _hoisted_31 = { class: "cleanup-fields" };
const _hoisted_32 = { class: "vertical-actions" };
const _hoisted_33 = { class: "history-list" };
const _hoisted_34 = ["href"];
const _hoisted_35 = { key: 1 };
const _hoisted_36 = {
  key: 0,
  class: "empty-table"
};
const _hoisted_37 = { class: "settings-grid" };
const _hoisted_38 = { class: "settings-actions" };
const _hoisted_39 = {
  key: 1,
  class: "empty-state empty-workspace"
};
const _hoisted_40 = { class: "rule-grid auth-grid" };

const {computed,inject,onMounted,ref,watch} = await importShared('vue');


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
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const activeTab = ref(props.initialTab);
const selectedSiteId = ref('');
const deleteSiteDialog = ref(false);
const authRule = ref(null);
const authDialog = computed({
  get: () => Boolean(authRule.value),
  set: value => { if (!value) authRule.value = null; },
});
const status = ref({ settings: { sites: [] }, sites: [], tasks: [], history: [], downloaders: [] });
const draft = ref({ sites: [] });

const sites = computed(() => draft.value.sites || []);
const selectedSite = computed(() => sites.value.find(site => site.id === selectedSiteId.value) || null);
const selectedSummary = computed(() => status.value.sites?.find(site => site.id === selectedSiteId.value) || {});
const taskNameOptions = computed(() => selectedSite.value?.rss_rules?.map(rule => rule.name).filter(Boolean) || []);
const downloaderLabel = computed(() => draft.value.downloader_mode === 'custom'
  ? (draft.value.custom_qb_url || '自定义 qBittorrent')
  : (draft.value.downloader || '尚未选择下载器'));

const resolutionOptions = ['8K', '4K', '1080P', '1080I', '720P', '576P', '480P'];
const promotionOptions = [
  { title: '不限促销', value: 'any' },
  { title: '仅免费', value: 'free' },
  { title: '免费或双倍上传免费', value: 'free_or_2xfree' },
  { title: '仅双倍上传免费', value: '2xfree' },
];
const taskHeaders = [
  { title: '任务', key: 'name', sortable: false },
  { title: '进度', key: 'progress', sortable: false },
  { title: '状态', key: 'state', sortable: false },
  { title: '分享率', key: 'ratio', sortable: false },
  { title: '速度', key: 'speed', sortable: false },
  { title: '免费截止', key: 'free_until', sortable: false },
];

function unwrap(response) {
  if (response?.success === false) throw new Error(response.message || '操作失败')
  return response?.data ?? response
}

function notify(message, kind = 'success') {
  if (typeof hostToast?.[kind] === 'function') hostToast[kind](message);
  else if (kind === 'error') error.value = message;
}

function uid() {
  return globalThis.crypto?.randomUUID?.().replaceAll('-', '') || `${Date.now()}${Math.random()}`.replace('.', '')
}

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function siteColor(index) {
  return ['#6d4aff', '#00897b', '#d96c00', '#0277bd', '#c62828', '#6d4c41'][index % 6]
}

async function loadStatus(preserveDraft = false) {
  loading.value = true;
  error.value = '';
  try {
    const query = selectedSiteId.value ? `?site_id=${encodeURIComponent(selectedSiteId.value)}` : '';
    status.value = unwrap(await props.api.get(`${pluginBase}/status${query}`));
    if (!preserveDraft) draft.value = clone(status.value.settings || { sites: [] });
    const exists = sites.value.some(site => site.id === selectedSiteId.value);
    if (!exists) selectedSiteId.value = sites.value[0]?.id || '';
  } catch (err) {
    error.value = err?.message || '加载刷流追新失败';
  } finally {
    loading.value = false;
  }
}

async function selectSite(siteId) {
  selectedSiteId.value = siteId;
  await loadStatus(true);
}

function addSite() {
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
    uid: '', passkey: '', cookie: '', user_agent: '', referer: '', use_proxy: null,
    required_keywords: [], excluded_keywords: [], resolutions: [], promotion: 'any',
    publish_age_from_minutes: null, publish_age_to_minutes: null,
    size_from_gib: null, size_to_gib: null,
  });
}

function openAuthPage(rule) {
  authRule.value = rule;
}

function addCleanupRule() {
  selectedSite.value.cleanup_rules.push({
    id: uid(), name: `删种规则 ${selectedSite.value.cleanup_rules.length + 1}`, enabled: true,
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
  const [removed] = selectedSite.value.rss_rules.splice(index, 1);
  selectedSite.value.cleanup_rules.forEach(rule => {
    rule.labels = (rule.labels || []).filter(label => label !== removed?.name);
  });
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
  saving.value = true;
  try {
    const payload = clone(draft.value);
    const rangeFields = [
      'publish_age_from_minutes', 'publish_age_to_minutes', 'size_from_gib', 'size_to_gib',
    ];
    payload.sites.forEach(site => site.rss_rules.forEach(rule => {
      rangeFields.forEach(key => { if (rule[key] === '') rule[key] = null; });
    }));
    status.value = unwrap(await props.api.post(`${pluginBase}/settings`, payload));
    draft.value = clone(status.value.settings);
    await loadStatus(true);
    notify('配置已保存，定时任务已更新');
    emit('action');
  } catch (err) {
    notify(err?.message || '保存配置失败', 'error');
  } finally {
    saving.value = false;
  }
}

async function runOperation(operation) {
  saving.value = true;
  try {
    unwrap(await props.api.post(`${pluginBase}/run`, { operation, site_id: selectedSiteId.value || null }));
    notify('任务已提交到后台');
  } catch (err) {
    notify(err?.message || '提交任务失败', 'error');
  } finally {
    saving.value = false;
  }
}

async function testDownloader() {
  saving.value = true;
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
    notify(`连接正常，当前 ${data.torrent_count} 个任务`);
  } catch (err) {
    notify(err?.message || 'qBittorrent 连接失败', 'error');
  } finally {
    saving.value = false;
  }
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function formatDuration(seconds) {
  const hours = Math.floor(Number(seconds || 0) / 3600);
  if (hours >= 24) return `${Math.floor(hours / 24)} 天 ${hours % 24} 小时`
  return `${hours} 小时`
}

watch(() => props.initialTab, value => { if (value) activeTab.value = value; });
onMounted(() => loadStatus());

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VTooltip = _resolveComponent("VTooltip");
  const _component_VAlert = _resolveComponent("VAlert");
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

  return (_openBlock(), _createElementBlock("div", {
    class: _normalizeClass(["tracker", { 'tracker--compact': __props.compact }])
  }, [
    _createElementVNode("header", _hoisted_1, [
      _createElementVNode("div", _hoisted_2, [
        _createVNode(_component_VIcon, {
          icon: "mdi-rss-box",
          color: "primary",
          size: "30"
        }),
        _cache[39] || (_cache[39] = _createElementVNode("div", null, [
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
              loading: loading.value,
              onClick: _cache[0] || (_cache[0] = $event => (loadStatus()))
            }), null, 16, ["loading"])
          ]),
          _: 1
        }),
        _createVNode(_component_VBtn, {
          color: "primary",
          variant: "flat",
          "prepend-icon": "mdi-content-save",
          loading: saving.value,
          onClick: saveSettings
        }, {
          default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
            _createTextVNode("保存", -1)
          ]))]),
          _: 1
        }, 8, ["loading"]),
        (__props.showClose)
          ? (_openBlock(), _createBlock(_component_VTooltip, {
              key: 0,
              text: "关闭"
            }, {
              activator: _withCtx(({ props: tip }) => [
                _createVNode(_component_VBtn, _mergeProps(tip, {
                  icon: "mdi-close",
                  variant: "text",
                  onClick: _cache[1] || (_cache[1] = $event => (_ctx.$emit('close')))
                }), null, 16)
              ]),
              _: 1
            }))
          : _createCommentVNode("", true)
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          closable: "",
          "onClick:close": _cache[2] || (_cache[2] = $event => (error.value = ''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (status.value.downloader_error)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "warning",
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(status.value.downloader_error), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (loading.value && !sites.value.length)
      ? (_openBlock(), _createElementBlock("div", _hoisted_4, [
          _createVNode(_component_VSkeletonLoader, { type: "list-item-three-line, article" })
        ]))
      : (_openBlock(), _createElementBlock("div", _hoisted_5, [
          _createVNode(_component_VSheet, {
            tag: "aside",
            class: "site-rail app-surface-static"
          }, {
            default: _withCtx(() => [
              _cache[43] || (_cache[43] = _createElementVNode("div", { class: "site-rail__head" }, [
                _createElementVNode("strong", null, "站点")
              ], -1)),
              _createElementVNode("div", _hoisted_6, [
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
                  ], 14, _hoisted_7))
                }), 128)),
                _createElementVNode("button", {
                  type: "button",
                  class: "site-item site-add",
                  style: {"--site-color":"#6d4aff"},
                  onClick: addSite
                }, [
                  _createElementVNode("span", null, [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-plus",
                      size: "18"
                    }),
                    _cache[41] || (_cache[41] = _createTextVNode("新增站点", -1))
                  ]),
                  _cache[42] || (_cache[42] = _createElementVNode("small", null, "创建新的站点配置", -1))
                ])
              ])
            ]),
            _: 1
          }),
          _createElementVNode("main", _hoisted_8, [
            _createVNode(_component_VSelect, {
              class: "mobile-site",
              "model-value": selectedSiteId.value,
              items: sites.value,
              "item-title": "name",
              "item-value": "id",
              label: "当前站点",
              "hide-details": "",
              "onUpdate:modelValue": selectSite
            }, null, 8, ["model-value", "items"]),
            (selectedSite.value)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createElementVNode("div", _hoisted_9, [
                    _createElementVNode("div", _hoisted_10, [
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
                    _createElementVNode("div", _hoisted_11, [
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
                  ]),
                  _createVNode(_component_VTabs, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((activeTab).value = $event)),
                    class: "tracker-tabs",
                    "show-arrows": ""
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VTab, {
                        value: "tasks",
                        "prepend-icon": "mdi-download-network-outline"
                      }, {
                        default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                          _createTextVNode("任务", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_VTab, {
                        value: "rss",
                        "prepend-icon": "mdi-rss"
                      }, {
                        default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
                          _createTextVNode("RSS 任务", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_VTab, {
                        value: "cleanup",
                        "prepend-icon": "mdi-broom"
                      }, {
                        default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
                          _createTextVNode("删种规则", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_VTab, {
                        value: "history",
                        "prepend-icon": "mdi-history"
                      }, {
                        default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                          _createTextVNode("记录", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_VTab, {
                        value: "settings",
                        "prepend-icon": "mdi-tune-variant"
                      }, {
                        default: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                          _createTextVNode("全局设置", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"]),
                  _createVNode(_component_VWindow, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((activeTab).value = $event)),
                    class: "tracker-window"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VWindowItem, { value: "tasks" }, {
                        default: _withCtx(() => [
                          _createElementVNode("div", _hoisted_12, [
                            _createVNode(_component_VSheet, { class: "stat app-surface-static" }, {
                              default: _withCtx(() => [
                                _cache[49] || (_cache[49] = _createElementVNode("span", null, "托管任务", -1)),
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
                                _cache[50] || (_cache[50] = _createElementVNode("span", null, "RSS 任务", -1)),
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
                                _cache[51] || (_cache[51] = _createElementVNode("span", null, "最近读取", -1)),
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
                                _cache[52] || (_cache[52] = _createElementVNode("span", null, "最近添加", -1)),
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
                              _createElementVNode("header", _hoisted_13, [
                                _createElementVNode("div", null, [
                                  _cache[53] || (_cache[53] = _createElementVNode("h2", null, "本插件托管的 qBittorrent 任务", -1)),
                                  _createElementVNode("p", null, _toDisplayString(downloaderLabel.value), 1)
                                ]),
                                _createElementVNode("div", null, [
                                  _createVNode(_component_VBtn, {
                                    variant: "tonal",
                                    "prepend-icon": "mdi-rss",
                                    loading: saving.value,
                                    onClick: _cache[7] || (_cache[7] = $event => (runOperation('rss')))
                                  }, {
                                    default: _withCtx(() => [...(_cache[54] || (_cache[54] = [
                                      _createTextVNode("立即刷新", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading"]),
                                  _createVNode(_component_VBtn, {
                                    variant: "text",
                                    "prepend-icon": "mdi-broom",
                                    loading: saving.value,
                                    onClick: _cache[8] || (_cache[8] = $event => (runOperation('cleanup')))
                                  }, {
                                    default: _withCtx(() => [...(_cache[55] || (_cache[55] = [
                                      _createTextVNode("检查删种", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading"])
                                ])
                              ]),
                              _createVNode(_component_VDataTable, {
                                headers: taskHeaders,
                                items: status.value.tasks || [],
                                loading: loading.value,
                                density: "comfortable",
                                class: "task-table"
                              }, {
                                "item.name": _withCtx(({ item }) => [
                                  _createElementVNode("div", _hoisted_14, [
                                    _createElementVNode("strong", null, _toDisplayString(item.name), 1),
                                    _createElementVNode("small", null, _toDisplayString(formatBytes(item.size)) + " · " + _toDisplayString(item.tags.join(', ')), 1)
                                  ])
                                ]),
                                "item.progress": _withCtx(({ item }) => [
                                  _createElementVNode("div", _hoisted_15, [
                                    _createElementVNode("span", null, _toDisplayString(item.progress) + "%", 1),
                                    _createVNode(_component_VProgressLinear, {
                                      "model-value": item.progress,
                                      height: "5",
                                      rounded: "",
                                      color: "primary"
                                    }, null, 8, ["model-value"])
                                  ])
                                ]),
                                "item.ratio": _withCtx(({ item }) => [
                                  _createTextVNode(_toDisplayString(Number(item.ratio || 0).toFixed(2)), 1),
                                  _createElementVNode("small", _hoisted_16, _toDisplayString(formatDuration(item.seeding_time)), 1)
                                ]),
                                "item.speed": _withCtx(({ item }) => [
                                  _createElementVNode("span", null, "↓ " + _toDisplayString(formatBytes(item.dlspeed)) + "/s", 1),
                                  _createElementVNode("small", _hoisted_17, "↑ " + _toDisplayString(formatBytes(item.upspeed)) + "/s", 1)
                                ]),
                                "item.free_until": _withCtx(({ item }) => [
                                  _createElementVNode("span", {
                                    class: _normalizeClass({ 'text-warning': item.free_until })
                                  }, _toDisplayString(formatTime(item.free_until)), 3)
                                ]),
                                "no-data": _withCtx(() => [...(_cache[56] || (_cache[56] = [
                                  _createElementVNode("div", { class: "empty-table" }, "当前站点没有托管任务", -1)
                                ]))]),
                                _: 1
                              }, 8, ["items", "loading"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VWindowItem, { value: "rss" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _createElementVNode("header", _hoisted_18, [
                                _cache[58] || (_cache[58] = _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "RSS 选种任务"),
                                  _createElementVNode("p", null, "任务名会自动作为 qBittorrent 标签；未选择分辨率时参与最高画质去重")
                                ], -1)),
                                _createVNode(_component_VBtn, {
                                  color: "primary",
                                  variant: "tonal",
                                  "prepend-icon": "mdi-plus",
                                  onClick: addRssRule
                                }, {
                                  default: _withCtx(() => [...(_cache[57] || (_cache[57] = [
                                    _createTextVNode("新增任务", -1)
                                  ]))]),
                                  _: 1
                                })
                              ]),
                              (!selectedSite.value.rss_rules.length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_19, [
                                    _createVNode(_component_VIcon, {
                                      icon: "mdi-rss-off",
                                      size: "46"
                                    }),
                                    _cache[60] || (_cache[60] = _createElementVNode("strong", null, "尚未配置 RSS 任务", -1)),
                                    _createVNode(_component_VBtn, {
                                      variant: "tonal",
                                      onClick: addRssRule
                                    }, {
                                      default: _withCtx(() => [...(_cache[59] || (_cache[59] = [
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
                                                _createElementVNode("div", _hoisted_20, [
                                                  _createVNode(_component_VIcon, {
                                                    icon: "mdi-rss",
                                                    color: "info"
                                                  }),
                                                  _createElementVNode("strong", null, _toDisplayString(rule.name || `RSS 任务 ${index + 1}`), 1),
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
                                                _createElementVNode("div", _hoisted_21, [
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
                                                    modelValue: rule.required_keywords,
                                                    "onUpdate:modelValue": $event => ((rule.required_keywords) = $event),
                                                    label: "必须包含关键词",
                                                    multiple: "",
                                                    chips: "",
                                                    "closable-chips": "",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VCombobox, {
                                                    modelValue: rule.excluded_keywords,
                                                    "onUpdate:modelValue": $event => ((rule.excluded_keywords) = $event),
                                                    label: "排除关键词",
                                                    multiple: "",
                                                    chips: "",
                                                    "closable-chips": "",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VSelect, {
                                                    modelValue: rule.resolutions,
                                                    "onUpdate:modelValue": $event => ((rule.resolutions) = $event),
                                                    items: resolutionOptions,
                                                    label: "分辨率筛选",
                                                    multiple: "",
                                                    chips: "",
                                                    "closable-chips": "",
                                                    clearable: "",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createVNode(_component_VSelect, {
                                                    modelValue: rule.promotion,
                                                    "onUpdate:modelValue": $event => ((rule.promotion) = $event),
                                                    items: promotionOptions,
                                                    label: "免费期筛选",
                                                    "hide-details": ""
                                                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                  _createElementVNode("div", _hoisted_22, [
                                                    _cache[62] || (_cache[62] = _createElementVNode("span", null, "发种时间范围（分钟）", -1)),
                                                    _createElementVNode("div", _hoisted_23, [
                                                      _createVNode(_component_VTextField, {
                                                        modelValue: rule.publish_age_from_minutes,
                                                        "onUpdate:modelValue": $event => ((rule.publish_age_from_minutes) = $event),
                                                        modelModifiers: { number: true },
                                                        type: "number",
                                                        min: "0",
                                                        label: "从",
                                                        suffix: "分钟",
                                                        clearable: "",
                                                        "hide-details": ""
                                                      }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                      _cache[61] || (_cache[61] = _createElementVNode("b", null, "至", -1)),
                                                      _createVNode(_component_VTextField, {
                                                        modelValue: rule.publish_age_to_minutes,
                                                        "onUpdate:modelValue": $event => ((rule.publish_age_to_minutes) = $event),
                                                        modelModifiers: { number: true },
                                                        type: "number",
                                                        min: "0",
                                                        label: "到",
                                                        suffix: "分钟",
                                                        clearable: "",
                                                        "hide-details": ""
                                                      }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                                    ])
                                                  ]),
                                                  _createElementVNode("div", _hoisted_24, [
                                                    _cache[64] || (_cache[64] = _createElementVNode("span", null, "文件大小范围（GiB）", -1)),
                                                    _createElementVNode("div", _hoisted_25, [
                                                      _createVNode(_component_VTextField, {
                                                        modelValue: rule.size_from_gib,
                                                        "onUpdate:modelValue": $event => ((rule.size_from_gib) = $event),
                                                        modelModifiers: { number: true },
                                                        type: "number",
                                                        min: "0",
                                                        step: "0.1",
                                                        label: "从",
                                                        suffix: "GiB",
                                                        clearable: "",
                                                        "hide-details": ""
                                                      }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                                      _cache[63] || (_cache[63] = _createElementVNode("b", null, "至", -1)),
                                                      _createVNode(_component_VTextField, {
                                                        modelValue: rule.size_to_gib,
                                                        "onUpdate:modelValue": $event => ((rule.size_to_gib) = $event),
                                                        modelModifiers: { number: true },
                                                        type: "number",
                                                        min: "0",
                                                        step: "0.1",
                                                        label: "到",
                                                        suffix: "GiB",
                                                        clearable: "",
                                                        "hide-details": ""
                                                      }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                                    ])
                                                  ])
                                                ]),
                                                _createElementVNode("div", _hoisted_26, [
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
                                                    default: _withCtx(() => [...(_cache[65] || (_cache[65] = [
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
                                                    default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
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
                      }),
                      _createVNode(_component_VWindowItem, { value: "cleanup" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _createElementVNode("header", _hoisted_27, [
                                _cache[68] || (_cache[68] = _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "顺序删种规则"),
                                  _createElementVNode("p", null, "每个任务只执行第一条标签与阈值均命中的规则")
                                ], -1)),
                                _createVNode(_component_VBtn, {
                                  color: "primary",
                                  variant: "tonal",
                                  "prepend-icon": "mdi-plus",
                                  onClick: addCleanupRule
                                }, {
                                  default: _withCtx(() => [...(_cache[67] || (_cache[67] = [
                                    _createTextVNode("新增规则", -1)
                                  ]))]),
                                  _: 1
                                })
                              ]),
                              (!selectedSite.value.cleanup_rules.length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_28, [
                                    _createVNode(_component_VIcon, {
                                      icon: "mdi-broom",
                                      size: "46"
                                    }),
                                    _cache[70] || (_cache[70] = _createElementVNode("strong", null, "尚未配置自动删种", -1)),
                                    _createVNode(_component_VBtn, {
                                      variant: "tonal",
                                      onClick: addCleanupRule
                                    }, {
                                      default: _withCtx(() => [...(_cache[69] || (_cache[69] = [
                                        _createTextVNode("新增规则", -1)
                                      ]))]),
                                      _: 1
                                    })
                                  ]))
                                : (_openBlock(), _createElementBlock("div", _hoisted_29, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selectedSite.value.cleanup_rules, (rule, index) => {
                                      return (_openBlock(), _createBlock(_component_VSheet, {
                                        key: rule.id,
                                        class: "cleanup-rule"
                                      }, {
                                        default: _withCtx(() => [
                                          _createElementVNode("div", _hoisted_30, _toDisplayString(index + 1), 1),
                                          _createElementVNode("div", _hoisted_31, [
                                            _createVNode(_component_VTextField, {
                                              modelValue: rule.name,
                                              "onUpdate:modelValue": $event => ((rule.name) = $event),
                                              label: "规则名称",
                                              "hide-details": ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                            _createVNode(_component_VSelect, {
                                              modelValue: rule.labels,
                                              "onUpdate:modelValue": $event => ((rule.labels) = $event),
                                              items: taskNameOptions.value,
                                              label: "适用任务标签（任一匹配）",
                                              multiple: "",
                                              chips: "",
                                              "closable-chips": "",
                                              "hide-details": ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue", "items"]),
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
                                              "hide-details": "",
                                              color: "success",
                                              inset: ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                            _createVNode(_component_VSwitch, {
                                              modelValue: rule.delete_files,
                                              "onUpdate:modelValue": $event => ((rule.delete_files) = $event),
                                              label: "同时删除文件",
                                              "hide-details": "",
                                              color: "error",
                                              inset: ""
                                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                          ]),
                                          _createElementVNode("div", _hoisted_32, [
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
                      }),
                      _createVNode(_component_VWindowItem, { value: "history" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _cache[71] || (_cache[71] = _createElementVNode("header", { class: "panel__head" }, [
                                _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "处理记录"),
                                  _createElementVNode("p", null, "最近 100 条添加与删除结果；点击种子名称进入站点详情页")
                                ])
                              ], -1)),
                              _createElementVNode("div", _hoisted_33, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(status.value.history || [], (row) => {
                                  return (_openBlock(), _createElementBlock("article", {
                                    key: `${row.time}-${row.title}`
                                  }, [
                                    _createVNode(_component_VIcon, {
                                      icon: row.event === 'added' ? 'mdi-download-circle-outline' : 'mdi-delete-circle-outline',
                                      color: row.event === 'added' ? 'success' : 'warning'
                                    }, null, 8, ["icon", "color"]),
                                    _createElementVNode("div", null, [
                                      (row.link)
                                        ? (_openBlock(), _createElementBlock("a", {
                                            key: 0,
                                            href: row.link,
                                            target: "_blank",
                                            rel: "noopener noreferrer"
                                          }, _toDisplayString(row.title), 9, _hoisted_34))
                                        : (_openBlock(), _createElementBlock("strong", _hoisted_35, _toDisplayString(row.title), 1)),
                                      _createElementVNode("span", null, _toDisplayString(row.reason || `${row.rule_name || 'RSS 任务'} · ${row.resolution || '未知画质'}`), 1)
                                    ]),
                                    _createElementVNode("time", null, _toDisplayString(formatTime(row.time)), 1)
                                  ]))
                                }), 128)),
                                (!status.value.history?.length)
                                  ? (_openBlock(), _createElementBlock("div", _hoisted_36, "暂无处理记录"))
                                  : _createCommentVNode("", true)
                              ])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VWindowItem, { value: "settings" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSheet, { class: "panel app-surface-static" }, {
                            default: _withCtx(() => [
                              _cache[75] || (_cache[75] = _createElementVNode("header", { class: "panel__head" }, [
                                _createElementVNode("div", null, [
                                  _createElementVNode("h2", null, "全局连接与调度"),
                                  _createElementVNode("p", null, "所有站点共用这一项 qBittorrent 配置")
                                ])
                              ], -1)),
                              _createElementVNode("div", _hoisted_37, [
                                _createVNode(_component_VSwitch, {
                                  modelValue: draft.value.enabled,
                                  "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((draft.value.enabled) = $event)),
                                  label: "启用插件",
                                  color: "success",
                                  "hide-details": "",
                                  inset: ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VSwitch, {
                                  modelValue: draft.value.show_sidebar_nav,
                                  "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((draft.value.show_sidebar_nav) = $event)),
                                  label: "显示侧栏入口",
                                  "hide-details": "",
                                  inset: ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VSelect, {
                                  modelValue: draft.value.downloader_mode,
                                  "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((draft.value.downloader_mode) = $event)),
                                  items: [{ title: 'MoviePilot 内置下载器', value: 'moviepilot' }, { title: '自定义 qBittorrent', value: 'custom' }],
                                  label: "qBittorrent 连接方式",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                (draft.value.downloader_mode !== 'custom')
                                  ? (_openBlock(), _createBlock(_component_VSelect, {
                                      key: 0,
                                      modelValue: draft.value.downloader,
                                      "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((draft.value.downloader) = $event)),
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
                                              loading: saving.value,
                                              onClick: testDownloader
                                            }), null, 16, ["loading"])
                                          ]),
                                          _: 1
                                        })
                                      ]),
                                      _: 1
                                    }, 8, ["modelValue", "items"]))
                                  : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                                      _createVNode(_component_VTextField, {
                                        modelValue: draft.value.custom_qb_url,
                                        "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((draft.value.custom_qb_url) = $event)),
                                        label: "qBittorrent WebUI 地址",
                                        placeholder: "http://127.0.0.1:8080",
                                        "hide-details": ""
                                      }, null, 8, ["modelValue"]),
                                      _createVNode(_component_VTextField, {
                                        modelValue: draft.value.custom_qb_username,
                                        "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((draft.value.custom_qb_username) = $event)),
                                        label: "qBittorrent 用户名",
                                        "hide-details": ""
                                      }, null, 8, ["modelValue"]),
                                      _createVNode(_component_VTextField, {
                                        modelValue: draft.value.custom_qb_password,
                                        "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((draft.value.custom_qb_password) = $event)),
                                        type: "password",
                                        label: "qBittorrent 密码",
                                        "hide-details": ""
                                      }, null, 8, ["modelValue"]),
                                      _createVNode(_component_VTextField, {
                                        modelValue: draft.value.custom_qb_save_path,
                                        "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((draft.value.custom_qb_save_path) = $event)),
                                        class: "span-2",
                                        label: "下载保存路径（可选）",
                                        placeholder: "/downloads 或 D:\\\\Downloads",
                                        "hide-details": ""
                                      }, null, 8, ["modelValue"]),
                                      _createVNode(_component_VBtn, {
                                        class: "span-2",
                                        variant: "tonal",
                                        "prepend-icon": "mdi-connection",
                                        loading: saving.value,
                                        onClick: testDownloader
                                      }, {
                                        default: _withCtx(() => [...(_cache[72] || (_cache[72] = [
                                          _createTextVNode("测试自定义 qBittorrent 连接", -1)
                                        ]))]),
                                        _: 1
                                      }, 8, ["loading"])
                                    ], 64)),
                                _createVNode(_component_VSwitch, {
                                  modelValue: draft.value.highest_resolution_dedup,
                                  "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((draft.value.highest_resolution_dedup) = $event)),
                                  class: "span-2",
                                  label: "同一影视仅下载最高分辨率",
                                  color: "primary",
                                  "hide-details": "",
                                  inset: ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: draft.value.rss_interval_minutes,
                                  "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((draft.value.rss_interval_minutes) = $event)),
                                  modelModifiers: { number: true },
                                  type: "number",
                                  min: "1",
                                  label: "RSS 刷新间隔（分钟）",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: draft.value.free_monitor_interval_minutes,
                                  "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((draft.value.free_monitor_interval_minutes) = $event)),
                                  modelModifiers: { number: true },
                                  type: "number",
                                  min: "1",
                                  label: "免费期检查间隔（分钟）",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: draft.value.cleanup_interval_minutes,
                                  "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((draft.value.cleanup_interval_minutes) = $event)),
                                  modelModifiers: { number: true },
                                  type: "number",
                                  min: "1",
                                  label: "自动删种间隔（分钟）",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: draft.value.request_timeout_seconds,
                                  "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((draft.value.request_timeout_seconds) = $event)),
                                  modelModifiers: { number: true },
                                  type: "number",
                                  min: "5",
                                  max: "120",
                                  label: "RSS 请求超时（秒）",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: draft.value.history_limit,
                                  "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((draft.value.history_limit) = $event)),
                                  modelModifiers: { number: true },
                                  type: "number",
                                  min: "50",
                                  max: "5000",
                                  label: "历史记录上限",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VSwitch, {
                                  modelValue: selectedSite.value.use_proxy,
                                  "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((selectedSite.value.use_proxy) = $event)),
                                  label: "当前站点 RSS 使用代理",
                                  "hide-details": "",
                                  inset: ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: selectedSite.value.user_agent,
                                  "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((selectedSite.value.user_agent) = $event)),
                                  class: "span-2",
                                  label: "当前站点自定义 User-Agent",
                                  clearable: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: selectedSite.value.uid,
                                  "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((selectedSite.value.uid) = $event)),
                                  label: "站点 UID（可选）",
                                  hint: "会自动补到 RSS/详情地址",
                                  "persistent-hint": "",
                                  "hide-details": "auto"
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VTextField, {
                                  modelValue: selectedSite.value.passkey,
                                  "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((selectedSite.value.passkey) = $event)),
                                  label: "站点 Passkey（可选）",
                                  hint: "用于站点身份识别，降低 403",
                                  "persistent-hint": "",
                                  "hide-details": "auto"
                                }, null, 8, ["modelValue"])
                              ]),
                              _createElementVNode("div", _hoisted_38, [
                                _createVNode(_component_VBtn, {
                                  color: "primary",
                                  variant: "flat",
                                  "prepend-icon": "mdi-content-save",
                                  loading: saving.value,
                                  onClick: saveSettings
                                }, {
                                  default: _withCtx(() => [...(_cache[73] || (_cache[73] = [
                                    _createTextVNode("保存全部设置", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["loading"]),
                                _createVNode(_component_VBtn, {
                                  variant: "tonal",
                                  "prepend-icon": "mdi-timer-refresh-outline",
                                  loading: saving.value,
                                  onClick: _cache[27] || (_cache[27] = $event => (runOperation('free_monitor')))
                                }, {
                                  default: _withCtx(() => [...(_cache[74] || (_cache[74] = [
                                    _createTextVNode("检查免费期", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["loading"])
                              ])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"])
                ], 64))
              : (_openBlock(), _createElementBlock("div", _hoisted_39, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-web-off",
                    size: "56"
                  }),
                  _cache[77] || (_cache[77] = _createElementVNode("strong", null, "还没有站点", -1)),
                  _createVNode(_component_VBtn, {
                    color: "primary",
                    variant: "flat",
                    "prepend-icon": "mdi-plus",
                    onClick: addSite
                  }, {
                    default: _withCtx(() => [...(_cache[76] || (_cache[76] = [
                      _createTextVNode("创建第一个站点", -1)
                    ]))]),
                    _: 1
                  })
                ]))
          ])
        ])),
    _createVNode(_component_VDialog, {
      modelValue: authDialog.value,
      "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((authDialog).value = $event)),
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
                    _cache[79] || (_cache[79] = _createElementVNode("p", { class: "block-muted auth-help" }, "此页面只作用于当前 RSS 任务。任务级填写优先于站点默认值；留空则继承站点设置或 MoviePilot 站点 Cookie。", -1)),
                    _createElementVNode("div", _hoisted_40, [
                      _createVNode(_component_VTextField, {
                        modelValue: authRule.value.uid,
                        "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((authRule.value.uid) = $event)),
                        label: "UID",
                        placeholder: "站点用户 UID",
                        "hide-details": ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_VTextField, {
                        modelValue: authRule.value.passkey,
                        "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((authRule.value.passkey) = $event)),
                        label: "Passkey",
                        type: "password",
                        placeholder: "站点 Passkey",
                        "hide-details": ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_VTextarea, {
                        modelValue: authRule.value.cookie,
                        "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((authRule.value.cookie) = $event)),
                        class: "span-2",
                        label: "Cookie（可选）",
                        placeholder: "从浏览器复制的完整 Cookie，例如 c_secure_uid=...; c_secure_pass=...",
                        rows: "3",
                        "auto-grow": "",
                        "hide-details": ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_VTextField, {
                        modelValue: authRule.value.user_agent,
                        "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((authRule.value.user_agent) = $event)),
                        label: "User-Agent（可选）",
                        placeholder: "留空使用站点/MoviePilot 默认值",
                        "hide-details": ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_VTextField, {
                        modelValue: authRule.value.referer,
                        "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((authRule.value.referer) = $event)),
                        label: "Referer（可选）",
                        placeholder: "https://站点域名/",
                        "hide-details": ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_VSwitch, {
                        modelValue: authRule.value.use_proxy,
                        "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((authRule.value.use_proxy) = $event)),
                        label: "此任务使用代理（留空继承站点）",
                        color: "primary",
                        inset: "",
                        "hide-details": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _createVNode(_component_VAlert, {
                      class: "auth-alert",
                      type: "info",
                      variant: "tonal",
                      density: "compact"
                    }, {
                      default: _withCtx(() => [...(_cache[78] || (_cache[78] = [
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
                      onClick: _cache[35] || (_cache[35] = $event => (authRule.value = null))
                    }, {
                      default: _withCtx(() => [...(_cache[80] || (_cache[80] = [
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
      "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((deleteSiteDialog).value = $event)),
      "max-width": "28rem"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, { title: "删除站点" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _createTextVNode("删除“" + _toDisplayString(selectedSite.value?.name) + "”及其所有规则？下载器中的现有任务不会被删除。", 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VCardActions, null, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[37] || (_cache[37] = $event => (deleteSiteDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[81] || (_cache[81] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "error",
                  variant: "flat",
                  onClick: confirmDeleteSite
                }, {
                  default: _withCtx(() => [...(_cache[82] || (_cache[82] = [
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
    }, 8, ["modelValue"])
  ], 2))
}
}

};
const Workbench = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-d2ea7793"]]);

export { Workbench as W };
