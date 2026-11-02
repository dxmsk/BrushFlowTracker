import test from 'node:test'
import assert from 'node:assert/strict'
import {
  clone, requestGate, prepareSettings, saveResolution, removeRssAndDisableReferences,
  taskState, taskTags, taskProgress, pauseExplanation, freeRemaining, ruleSummary,
  proxyOptions, normalizeJobs, reconcileJobs, validateSettings, unwrap,
} from './workbench.js'

const site = () => ({ id: 'a', name: '北站', rss_rules: [{ id: 'ra', name: 'A', use_proxy: null }, { id: 'rb', name: 'B', use_proxy: false }], cleanup_rules: [{ name: '关联 A', enabled: true, labels: ['A'] }, { name: '关联 AB', enabled: true, labels: ['A', 'B'] }, { name: '仅 B', enabled: true, labels: ['B'] }] })

test('request gates reject stale scope, stale errors/finally, and invalidated saves', () => {
  const gate = requestGate(), a = gate.begin('a'), b = gate.begin('b')
  assert.equal(gate.current(a, 'b'), false)
  assert.equal(gate.current(a, 'a'), false)
  assert.equal(gate.current(b, 'b'), true)
  gate.invalidate()
  assert.equal(gate.current(b, 'b'), false)
})
test('saving an old revision preserves newer inputs while recording the server baseline', () => {
  const current = { sites: [{ name: 'after request' }] }, sent = { sites: [{ name: 'sent' }] }
  const result = saveResolution(current, 4, 3, { sites: [{ name: 'normalized sent' }] }, sent)
  assert.equal(result.draft, current)
  assert.equal(result.saved.sites[0].name, 'normalized sent')
  assert.notEqual(saveResolution(current, 3, 3, sent, sent).draft, current)
})
test('RSS deletion disables every referencing cleanup rule, even when labels remain', () => {
  const value = site()
  assert.deepEqual(removeRssAndDisableReferences(value, 0), ['关联 A', '关联 AB'])
  assert.deepEqual(value.cleanup_rules.map(rule => [rule.enabled, rule.labels]), [[false, []], [false, ['B']], [true, ['B']]])
  assert.deepEqual(prepareSettings({ sites: [value] }).sites[0].cleanup_rules[0].labels, [])
})
test('payload keeps null/true/false proxy values and does not mutate the draft', () => {
  const value = { sites: [{ ...site(), rss_rules: [null, true, false].map(use_proxy => ({ name: String(use_proxy), use_proxy, size_from_value: '' })), cleanup_rules: [{ enabled: true, labels: [] }] }] }
  const copy = clone(value), payload = prepareSettings(value)
  assert.deepEqual(payload.sites[0].rss_rules.map(rule => rule.use_proxy), [null, true, false])
  assert.deepEqual(proxyOptions.map(option => option.value), [null, true, false])
  assert.equal(payload.sites[0].cleanup_rules[0].enabled, false)
  assert.equal(payload.sites[0].rss_rules[0].size_from_value, null)
  assert.deepEqual(value, copy)
})
test('running_jobs is authoritative beyond six seconds and queue gaps are not completion', () => {
  const pending = { rss: { site_id: 'a', submitted_at: 0, observed: false } }
  assert.ok(reconcileJobs(pending, {}, 10000).pending.rss)
  const seen = reconcileJobs(pending, { rss: { site_id: 'a' } }, 15000)
  assert.equal(seen.pending.rss.observed, true)
  assert.ok(reconcileJobs(seen.pending, { rss: { site_id: 'a' } }, 120000).pending.rss)
  assert.deepEqual(reconcileJobs(seen.pending, {}, 121000).finished, ['rss'])
  assert.deepEqual(reconcileJobs(pending, {}, 31000).unconfirmed, ['rss'])
  assert.deepEqual(reconcileJobs(pending, { rss: { site_id: 'b' } }, 10000).finished, [])
  assert.deepEqual(normalizeJobs([{ operation: 'rss', site_id: 'a' }]), { rss: { operation: 'rss', site_id: 'a' } })
})
test('task labels and paused explanations are localized without claiming a user pause', () => {
  for (const state of ['downloading', 'stalledDL', 'metaDL', 'forcedDL']) assert.equal(taskState({ state }).key, 'downloading')
  assert.equal(taskState({ state: 'pausedDL' }).title, '已暂停')
  assert.equal(taskState({ state: 'stoppedUP' }).title, '已暂停')
  assert.equal(taskState({ state: 'uploading' }).title, '做种中')
  assert.match(pauseExplanation({ state: 'pausedDL' }), /不能确定/)
  assert.match(pauseExplanation({ state: 'pausedDL', paused_by_plugin: true }), /插件暂停/)
  assert.deepEqual(taskTags({ tags: 'A, B' }), ['A', 'B'])
  assert.deepEqual(taskTags({}), [])
  assert.equal(taskProgress({ progress: 102 }), 100)
})
test('free expiry emphasizes only near deadlines and tolerates unknown values', () => {
  const now = Date.parse('2026-01-01T00:00:00Z')
  assert.equal(freeRemaining('2026-01-01T00:48:00Z', now).urgent, true)
  assert.equal(freeRemaining('2026-01-02T00:48:00Z', now).urgent, false)
  assert.equal(freeRemaining(null, now).urgent, false)
  assert.equal(freeRemaining('invalid', now).urgent, false)
})
test('rule summary preserves resolution, ranges, units, and promotion', () => {
  assert.match(ruleSummary({ resolutions: ['4K'], publish_age_from_value: 0, publish_age_to_value: 30, publish_age_from_unit: 'minutes', publish_age_to_unit: 'minutes', size_to_value: 30, size_to_unit: 'gib', promotion: 'free' }), /4K.*0分钟–30分钟.*30GB.*仅免费/)
})
test('all tabs are validated without relying on mounted Vuetify fields', () => {
  assert.equal(validateSettings({ sites: [] }), null)
  assert.equal(validateSettings({ sites: [site()] }), null)
  assert.equal(validateSettings({ sites: [], rss_interval_minutes: 0 }).tab, 'settings')
  const value = site()
  value.cleanup_rules[0].labels = []
  assert.equal(validateSettings({ sites: [value] }).tab, 'cleanup')
  value.cleanup_rules[0].enabled = false
  value.rss_rules[0] = { ...value.rss_rules[0], size_from_value: 2, size_from_unit: 'gib', size_to_value: 1024, size_to_unit: 'mib' }
  assert.match(validateSettings({ sites: [value] }).message, /起点不能大于终点/)
})
test('API errors retain validation details', () => {
  assert.throws(() => unwrap({ success: false, message: 'bad', detail: [{ loc: ['sites', 0] }] }), error => error.message === 'bad' && error.detail.length === 1)
})
