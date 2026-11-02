// Node-only SFC state tests: no browser, jsdom, new UI library, or backend needed.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRenderer, nextTick } from 'vue'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'

const filename = new URL('./Workbench.vue', import.meta.url)
const source = await readFile(filename, 'utf8')
const { descriptor, errors } = parse(source)
assert.deepEqual(errors, [])
const compiled = compileScript(descriptor, { id: 'workbench-test' })
const template = compileTemplate({ source: descriptor.template.content, filename: filename.pathname, id: 'workbench-test', compilerOptions: { bindingMetadata: compiled.bindings } })
assert.deepEqual(template.errors, [])
const script = compiled.content
  .replace(/import TaskTitle from ['"].*?['"]/, 'const TaskTitle = {}')
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replaceAll("'../utils/workbench.js'", `'${new URL('../utils/workbench.js', import.meta.url).href}'`)
const { default: Workbench } = await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)
const renderer = createRenderer({
  createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: text => ({ text }),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text },
  parentNode: node => node.parent, nextSibling: () => null, patchProp: () => {},
  insert(node, parent) { node.parent = parent; parent.children.push(node) },
  remove(node) { if (node.parent) node.parent.children = node.parent.children.filter(child => child !== node) },
})
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const settle = async () => { for (let i = 0; i < 12; i++) { await Promise.resolve(); await nextTick() } }
const makeSite = (id, name) => ({ id, name, enabled: true, rss_rules: [{ id: `${id}-rss`, name: '任务', enabled: true, url: '', use_proxy: null }], cleanup_rules: [{ id: `${id}-cleanup`, name: '清理', enabled: true, labels: ['任务'], min_seed_hours: 0, min_ratio: 0, delete_files: true }] })
const makeSettings = () => ({ sites: [makeSite('a', '北站'), makeSite('b', '南站')], downloader: 'qb', downloader_mode: 'moviepilot' })
function fixture(settings = makeSettings()) {
  const f = { settings, jobs: {}, posts: [], gets: [], override: null, postOverride: null }
  f.response = scope => ({ success: true, data: { settings: structuredClone(f.settings), sites: f.settings.sites.map(site => ({ id: site.id })), history: [{ title: scope || 'all', site_id: scope }], tasks: [], downloaders: ['qb'], running_jobs: structuredClone(f.jobs) } })
  f.api = {
    get(url) {
      f.gets.push(url)
      if (f.override) return f.override(url)
      const scope = new URL(url, 'https://mock/').searchParams.get('site_id')
      return Promise.resolve(url.includes('/tasks?') ? { success: true, data: { tasks: [{ name: scope, hash: scope, state: 'downloading', tags: ['任务'] }] } } : f.response(scope))
    },
    post(url, body) {
      f.posts.push({ url, body: structuredClone(body) })
      if (f.postOverride) return f.postOverride(url, body)
      if (url.endsWith('/settings')) { f.settings = structuredClone(body); return Promise.resolve(f.response('a')) }
      if (url.endsWith('/run')) f.jobs[body.operation] = { site_id: body.site_id, running_seconds: 0 }
      return Promise.resolve({ success: true, data: { torrent_count: 4 } })
    },
  }
  return f
}
function mount(t, f, initialTab = 'tasks') {
  const native = Object.fromEntries(['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'].map(key => [key, globalThis[key]]))
  const timers = new Map(), intervals = new Map(); let id = 0
  globalThis.setTimeout = (fn, delay) => { timers.set(++id, { fn, delay }); return id }
  globalThis.clearTimeout = value => timers.delete(value)
  globalThis.setInterval = (fn, delay) => { intervals.set(++id, { fn, delay }); return id }
  globalThis.clearInterval = value => intervals.delete(value)
  const app = renderer.createApp({ ...Workbench, render: () => null }, { api: f.api, initialTab })
  app.mount({ children: [] })
  const vm = app._instance.setupState
  t.after(() => { app.unmount(); Object.assign(globalThis, native) })
  return { vm, app, timers, intervals }
}

test('initial pending/failed status cannot submit a destructive empty settings payload', async t => {
  const f = fixture(), request = defer(); f.override = () => request.promise
  const { vm } = mount(t, f)
  assert.equal(vm.canSave, false)
  await vm.saveSettings()
  request.reject(new Error('offline')); await settle()
  assert.equal(vm.settingsLoaded, false)
  assert.equal(vm.canSave, false)
  await vm.saveSettings()
  assert.equal(f.posts.length, 0)
  assert.match(vm.statusError, /offline/)
})

test('fast site switching isolates status, tasks, errors, and finally flags', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  const requests = []
  f.override = url => { const d = defer(); requests.push({ url, ...d }); return d.promise }
  vm.selectSite('b'); vm.selectSite('a')
  assert.deepEqual(vm.status.history, [])
  assert.deepEqual(vm.status.tasks, [])
  const old = requests.find(req => req.url.includes('site_id=b'))
  const fresh = requests.find(req => req.url.includes('site_id=a'))
  old.reject(new Error('stale B failure')); await settle()
  assert.equal(vm.loading, true)
  assert.equal(vm.statusError, '')
  fresh.resolve(f.response('a')); await settle()
  assert.equal(vm.status.history[0].title, 'a')
  const taskA = requests.find(req => req.url.includes('/tasks?'))
  vm.selectSite('b')
  const latestB = requests.at(-1)
  taskA.resolve({ success: true, data: { tasks: [{ name: 'old A' }] } }); await settle()
  assert.deepEqual(vm.status.tasks, [])
  latestB.resolve(f.response('b')); await settle()
  const taskB = requests.at(-1)
  taskB.resolve({ success: true, data: { tasks: [{ name: 'new B' }] } }); await settle()
  assert.equal(vm.status.history[0].title, 'b')
  assert.equal(vm.status.tasks[0].name, 'new B')
})

test('older successful status cannot overwrite a newer site response', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  const a = defer(), b = defer()
  f.override = url => url.includes('/tasks?') ? Promise.resolve({ data: { tasks: [] } }) : url.includes('site_id=a') ? a.promise : b.promise
  vm.loadStatus(true, false); vm.selectSite('b')
  b.resolve(f.response('b')); await settle()
  a.resolve(f.response('a')); await settle()
  assert.equal(vm.selectedSiteId, 'b')
  assert.equal(vm.status.history[0].title, 'b')
})

test('save completion preserves edits made in flight and never merges first-site history', async t => {
  const f = fixture(), { vm, app } = mount(t, f); await settle()
  vm.selectSite('b'); await settle()
  vm.draft.sites[1].name = 'sent B'
  const save = defer()
  f.postOverride = (url, body) => { f.settings = structuredClone(body); return save.promise }
  const action = vm.saveSettings()
  assert.equal(vm.saving, true)
  assert.equal(vm.testing, false)
  vm.draft.sites[1].name = 'edited while saving'
  save.resolve(f.response('a')); await action; await settle()
  assert.equal(vm.draft.sites[1].name, 'edited while saving')
  assert.equal(vm.savedSettings.sites[1].name, 'sent B')
  assert.equal(vm.dirty, true)
  assert.equal(vm.status.history[0].title, 'b')
  assert.equal(vm.saving, false)
  assert.equal(app._instance.emitted?.action, undefined)
})

test('an in-flight status refresh cannot replace edits made after its request', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  const request = defer(); f.override = () => request.promise
  const loading = vm.loadStatus(true, false)
  vm.draft.sites[0].name = 'local draft'
  request.resolve(f.response('a')); await loading; await settle()
  assert.equal(vm.draft.sites[0].name, 'local draft')
  assert.equal(vm.dirty, true)
})

test('dirty run is rejected; save, test and run loading remain independent', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  vm.draft.sites[0].name = 'unsaved'
  await vm.runOperation('rss')
  assert.equal(f.posts.length, 0)
  assert.match(vm.runDisabledReason, /未保存/)
  const pendingTest = defer(); f.postOverride = () => pendingTest.promise
  const testAction = vm.testDownloader()
  assert.equal(vm.testing, true)
  assert.equal(vm.saving, false)
  assert.equal(vm.operationBusy('rss'), false)
  pendingTest.resolve({ success: true, data: { torrent_count: 9 } }); await testAction
  vm.discardChanges(); await settle(); f.postOverride = null
  await vm.runOperation('rss'); await settle()
  assert.deepEqual(f.posts.at(-1).body, { operation: 'rss', site_id: 'a' })
  assert.equal(vm.operationBusy('rss'), true)
  assert.equal(vm.saving, false)
  assert.equal(vm.testing, false)
})

test('cleanup needs confirmation of the same saved site and configuration', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  vm.requestCleanup()
  assert.equal(vm.cleanupDialog, true)
  assert.equal(vm.cleanupTarget.name, '北站')
  assert.equal(vm.cleanupTarget.deleteFiles, true)
  assert.equal(f.posts.length, 0)
  vm.draft.sites[0].name = 'changed'
  await vm.confirmCleanup()
  assert.equal(f.posts.length, 0)
  vm.discardChanges(); await settle()
  vm.requestCleanup(); await vm.confirmCleanup(); await settle()
  assert.deepEqual(f.posts.at(-1).body, { operation: 'cleanup', site_id: 'a' })
})

test('running_jobs stays tracked beyond six seconds and every timer is cleared on unmount', async t => {
  const f = fixture(), { vm, app, timers, intervals } = mount(t, f); await settle()
  await vm.runOperation('rss'); await settle()
  f.jobs.rss.running_seconds = 75
  await vm.loadStatus(true, false); await settle()
  assert.equal(vm.operationBusy('rss'), true)
  assert.ok(timers.size > 0)
  f.jobs = {}
  await vm.loadStatus(true, false); await settle()
  assert.equal(vm.operationBusy('rss'), false)
  assert.equal(timers.size, 0)
  await vm.runOperation('cleanup'); await settle()
  const callbacks = [...timers.values()].map(value => value.fn)
  app.unmount()
  assert.equal(timers.size, 0)
  assert.equal(intervals.size, 0)
  const count = f.gets.length
  for (const fn of callbacks) await fn()
  assert.equal(f.gets.length, count)
})

test('zero-site settings stay available and creating a site produces a protected draft', async t => {
  const f = fixture({ sites: [], downloader: 'qb' }), { vm } = mount(t, f, 'settings'); await settle()
  assert.equal(vm.activeTab, 'settings')
  assert.equal(vm.selectedSite, null)
  assert.equal(vm.settingsLoaded, true)
  vm.draft.downloader = 'new qb'
  assert.equal(vm.canSave, true)
  await vm.saveSettings(); await settle()
  assert.equal(f.settings.downloader, 'new qb')
  vm.addSite(); await settle()
  assert.equal(vm.sites.length, 1)
  assert.equal(vm.dirty, true)
  assert.equal(vm.activeTab, 'rss')
  assert.ok(vm.runDisabledReason)
})

test('task and history pagination clamp after filters shrink the result set', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  vm.status.tasks = Array.from({ length: 24 }, (_, i) => ({ name: `task ${i}`, state: i === 0 ? 'pausedDL' : 'downloading', tags: ['任务'] }))
  vm.taskPage = 3
  assert.equal(vm.pagedTasks.length, 4)
  vm.taskStateFilter = 'paused'; await settle()
  assert.equal(vm.taskPage, 1)
  assert.equal(vm.filteredTasks.length, 1)
  vm.status.history = Array.from({ length: 25 }, (_, i) => ({ title: `title ${i}`, outcome: i ? '下载' : '失败' }))
  vm.historyPage = 2
  assert.equal(vm.pagedHistory.length, 5)
  vm.historyFilter = '失败'; await settle()
  assert.equal(vm.historyPage, 1)
  assert.equal(vm.filteredHistory.length, 1)
})

test('a failed refresh disables saving without discarding a previously loaded draft', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  vm.draft.sites[0].name = 'keep me'
  f.override = () => Promise.reject(new Error('refresh offline'))
  await vm.loadStatus(true, false); await settle()
  assert.equal(vm.canSave, false)
  await vm.saveSettings()
  assert.equal(f.posts.length, 0)
  assert.equal(vm.draft.sites[0].name, 'keep me')
  f.override = null
  await vm.loadStatus(true, false); await settle()
  assert.equal(vm.canSave, true)
  assert.equal(vm.draft.sites[0].name, 'keep me')
})

test('empty cleanup labels are explicitly disabled and RSS deletion keeps other rules intact', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  vm.updateCleanupLabels(vm.selectedSite.cleanup_rules[0], [])
  assert.equal(vm.selectedSite.cleanup_rules[0].enabled, false)
  vm.discardChanges(); await settle()
  vm.removeRssRule(0)
  assert.equal(vm.selectedSite.cleanup_rules[0].enabled, false)
  assert.match(vm.referenceWarning, /自动停用/)
  vm.addCleanupRule()
  assert.equal(vm.selectedSite.cleanup_rules.at(-1).enabled, false)
})

test('background visibility stops timers and resumes only while mounted', async t => {
  const originalDocument = globalThis.document
  const listeners = new Map()
  globalThis.document = { hidden: false, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) }
  const f = fixture(), { vm, app, timers, intervals } = mount(t, f); await settle()
  t.after(() => { globalThis.document = originalDocument })
  await vm.runOperation('rss'); await settle()
  assert.ok(timers.size && intervals.size)
  globalThis.document.hidden = true
  listeners.get('visibilitychange')()
  assert.equal(timers.size, 0)
  assert.equal(intervals.size, 0)
  const count = f.gets.length
  await vm.syncPolling()
  assert.equal(f.gets.length, count)
  globalThis.document.hidden = false
  listeners.get('visibilitychange')(); await settle()
  assert.ok(f.gets.length > count)
  assert.ok(timers.size && intervals.size)
  app.unmount()
  assert.equal(listeners.size, 0)
})

test('polling budget stops frontend observation without cancelling the backend job', async t => {
  const originalNow = Date.now
  let clock = originalNow()
  Date.now = () => clock
  const f = fixture(), { vm, timers } = mount(t, f); await settle()
  t.after(() => { Date.now = originalNow })
  await vm.runOperation('rss'); await settle()
  clock += 15 * 60 * 1000 + 1
  vm.syncPolling()
  assert.equal(timers.size, 0)
  assert.match(vm.pollWarning, /15 分钟/)
  assert.ok(f.jobs.rss)
  assert.equal(f.posts.filter(post => post.url.endsWith('/run')).length, 1)
})

test('close requests and browser leave events protect unsaved edits', async t => {
  const f = fixture(), { vm } = mount(t, f); await settle()
  vm.draft.sites[0].name = 'draft'
  vm.requestClose()
  assert.equal(vm.leaveDialog, true)
  let prevented = false
  const event = { preventDefault: () => { prevented = true } }
  vm.beforeUnload(event)
  assert.equal(prevented, true)
  assert.equal(event.returnValue, '')
})

test('initial hidden host loads settings once without starting periodic polling', async t => {
  const previous = globalThis.document
  globalThis.document = { hidden: true, addEventListener() {}, removeEventListener() {} }
  t.after(() => { if (previous === undefined) delete globalThis.document; else globalThis.document = previous })
  const f = fixture(), { vm, timers, intervals } = mount(t, f)
  await settle()
  assert.equal(vm.settingsLoaded, true)
  assert.equal(vm.activeTab, 'tasks')
  assert.ok(f.gets.length > 0)
  assert.equal(timers.size, 0)
  assert.equal(intervals.size, 0)
})

test('pending configuration and a live worker prevent an overlapping manual operation', async t => {
  const f = fixture(), base = f.response
  f.response = scope => { const response = base(scope); response.data.config_pending = true; return response }
  const { vm } = mount(t, f); await settle()
  assert.match(vm.runDisabledReason, /后台任务结束后生效/)
  await vm.runOperation('rss')
  assert.equal(f.posts.length, 0)
  vm.status.config_pending = false
  vm.status.running_jobs = { cleanup: { site_id: 'a', running_seconds: 1 } }
  assert.match(vm.runDisabledReason, /后台任务正在执行/)
  await vm.runOperation('rss')
  assert.equal(f.posts.length, 0)
})
