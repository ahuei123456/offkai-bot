import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

async function hookHarness(kind: 'useAdminData' | 'useScanner') {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.checkin-hooks-'))
  fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
  fs.writeFileSync(path.join(dir, 'react.js'), `
    const states = [], refs = [], effects = []; let index = 0, refIndex = 0, effectIndex = 0;
    export function begin(seed = {}, event) { index = 0; refIndex = 0; effectIndex = 0;
      for (const [key, value] of Object.entries(seed)) states[Number(key)] = value;
      if (event !== undefined) refs[0] = { current: event }; }
    export function useState(initial) { const key = index++; if (!(key in states)) states[key] = initial;
      return [states[key], value => { states[key] = typeof value === 'function' ? value(states[key]) : value; }]; }
    export function useRef(initial) { return refs[refIndex++] ??= { current: initial }; }
    export function useCallback(fn) { return fn; }
    export function useEffect(fn, deps) { const key = effectIndex++; const old = effects[key];
      if (!old || !deps || deps.some((value, i) => value !== old.deps[i]))
        effects[key] = { fn, deps, pending: true, cleanup: old?.cleanup }; }
    export function runEffect(key) { const effect = effects[key];
      if (effect?.pending) { effect.cleanup?.(); effect.pending = false; effect.cleanup = effect.fn(); } }
    export function runEffects() { effects.forEach((_, key) => runEffect(key)); }
    export function cleanup() { effects.forEach(effect => effect.cleanup?.()); }
  `)
  fs.writeFileSync(path.join(dir, 'dom.js'), 'export function flushSync(fn) { fn(); }')
  fs.writeFileSync(path.join(dir, 'qr.js'), `export let decode;
    export class Html5Qrcode { async start(camera, options, callback) { decode = callback; }
      async stop() {} clear() {} }`)
  const compile = (source: string) => ts.transpileModule(fs.readFileSync(source, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  fs.writeFileSync(path.join(dir, 'checkin.js'), compile('app/lib/checkin.ts'))
  fs.writeFileSync(path.join(dir, 'scan.js'), compile('app/lib/scan.ts'))
  fs.writeFileSync(path.join(dir, 'hook.js'), compile(`app/hooks/${kind}.ts`)
    .replaceAll("from 'react'", "from './react.js'").replaceAll("from 'react-dom'", "from './dom.js'")
    .replaceAll("from '../lib/checkin'", "from './checkin.js'").replaceAll("from '../lib/scan'", "from './scan.js'")
    .replaceAll("import('html5-qrcode')", "import('./qr.js')"))
  // Runtime-selected isolated copies intentionally exercise real module callbacks.
  const react = await import(pathToFileURL(path.join(dir, 'react.js')).href)
  const hook = await import(pathToFileURL(path.join(dir, 'hook.js')).href)
  return { dir, react, hook }
}

const uid = '191524132624531458'
const stampA = '2026-10-01T00:00:00.123Z'
const stampB = '2026-10-02T00:00:00.654Z'
const attendee = { user_id: uid, username: 'Synthetic', display_name: null, extra_people: 0, extras_names: [],
  drinks: [], status: 'attending', registration_timestamp: stampA }
const record = { user_id: uid, event_name: 'Event A', name: 'Synthetic', registration_timestamp: stampA,
  checked_in_at: '2026-10-03T00:00:00Z' }

test('manual actions bind displayed rows and discard delayed event/registration mutations', async () => {
  const harness = await hookHarness('useAdminData')
  const previousFetch = globalThis.fetch
  try {
    const { begin, runEffect } = harness.react
    const { useAdminData } = harness.hook
    const render = function RenderAdmin(seed: Record<number, unknown> = {}, event?: string) {
      begin(seed, event)
      const result = useAdminData()
      runEffect(0) // Only synchronize attendee refs; networking effects are controlled below.
      return result
    }
    const posts: Record<string, unknown>[] = []
    globalThis.fetch = async (_url, options) => {
      posts.push(JSON.parse(options!.body as string))
      return Response.json({ record })
    }
    const initial = render({ 0: 'synthetic-key', 1: true, 4: 'Event A', 6: 'Event A', 7: [attendee] }, 'Event A')
    initial.changeEvent('Event B')
    const loading = render()
    assert.equal(loading.eventName, 'Event A', 'Old rows remain displayed while B loads')
    await loading.manualCheckin(uid, stampA)
    await loading.manualCheckout(uid, stampA)
    await initial.manualCheckin(uid, stampA)
    await initial.manualCheckout(uid, stampA)
    loading.applyScanCheckin(record)
    assert.equal(posts.length, 0)
    assert.deepEqual(render().checkins, {})

    loading.changeEvent('Event A')
    const loaded = render()
    await loaded.manualCheckin(uid, stampA)
    assert.equal(posts.length, 1)
    assert.deepEqual(posts[0], { user_id: uid, event_name: 'Event A', registration_timestamp: stampA })
    assert.equal(render().checkedInCount, 1)
    globalThis.fetch = async (_url, options) => {
      posts.push(JSON.parse(options!.body as string))
      return Response.json({ removed: true })
    }
    await render().manualCheckout(uid, stampA)
    assert.equal(render().checkedInCount, 0)
    assert.equal(posts[1].action, 'checkout')

    const pending: ((response: Response) => void)[] = []
    globalThis.fetch = async (_url, options) => {
      posts.push(JSON.parse(options!.body as string))
      return new Promise<Response>(resolve => pending.push(resolve))
    }
    const beforeSwitch = render()
    const checkin = beforeSwitch.manualCheckin(uid, stampA)
    beforeSwitch.changeEvent('Event B')
    let current = render({ 4: 'Event B', 7: [{ ...attendee, registration_timestamp: stampB }] })
    pending.shift()!(Response.json({ record }))
    await checkin
    assert.equal(render().checkedInCount, 0)
    beforeSwitch.applyScanCheckin(record)
    assert.deepEqual(render().checkins, {})

    // Returning to A must not resurrect a response from its previous selection.
    current.changeEvent('Event A')
    current = render({ 4: 'Event A', 7: [attendee], 8: { [uid]: record } })
    const checkout = current.manualCheckout(uid, stampA)
    current.changeEvent('Event B')
    render()
    current.changeEvent('Event A')
    render({ 4: 'Event A', 7: [attendee], 8: { [uid]: record } })
    pending.shift()!(Response.json({ removed: true }))
    await checkout
    assert.equal(render().checkedInCount, 1)
    const anotherCheckin = render().manualCheckin(uid, stampA)
    current.changeEvent('Event B')
    render()
    current.changeEvent('Event A')
    render({ 4: 'Event A', 7: [attendee], 8: {} })
    pending.shift()!(Response.json({ record }))
    await anotherCheckin
    assert.equal(render().checkedInCount, 0)

    // A registration refresh can independently race either manual response.
    const original = render()
    const oldCheckin = original.manualCheckin(uid, stampA)
    const replacement = { ...attendee, registration_timestamp: stampB, extra_people: 3 }
    render({ 7: [replacement] })
    pending.shift()!(Response.json({ record }))
    await oldCheckin
    let replaced = render()
    assert.equal(replaced.attendingCount, 4)
    assert.equal(replaced.checkedInCount, 0)
    assert.equal(replaced.pendingCount, 4)
    replaced.applyScanCheckin(record)
    assert.deepEqual(render().checkins, {})
    const replacementRecord = { ...record, registration_timestamp: stampB }
    replaced.applyScanCheckin(replacementRecord)
    assert.equal(render().checkedInCount, 4)
    const currentCheckout = render().manualCheckout(uid, stampB)
    const stampC = '2026-10-04T00:00:00.000Z'
    const latest = { ...replacement, registration_timestamp: stampC }
    const latestRecord = { ...record, registration_timestamp: stampC }
    render({ 7: [latest], 8: { [uid]: latestRecord } })
    pending.shift()!(Response.json({ removed: true }))
    await currentCheckout
    assert.equal(render().checkins[uid].registration_timestamp, stampC)
    // Legacy/stale records cannot enter rows, filters, or guest counters.
    const { registration_timestamp: _identity, ...legacy } = record
    replaced = render({ 7: [replacement], 8: { [uid]: legacy } })
    assert.equal(replaced.checkedInCount, 0)
    assert.equal(replaced.pendingCount, 4)
    replaced.changeFilter('checked')
    assert.deepEqual(render().filtered, [])
    replaced.changeFilter('pending')
    assert.equal(render().filtered.length, 1)
    replaced = render({ 8: { [uid]: record } })
    assert.equal(replaced.checkedInCount, 0)
    assert.deepEqual(replaced.checkins, {})
  } finally {
    globalThis.fetch = previousFetch
    harness.react.cleanup()
    fs.rmSync(harness.dir, { recursive: true, force: true })
  }
})

test('scanner ignores late A to B to A responses and stale registration results', async () => {
  const harness = await hookHarness('useScanner')
  const previousFetch = globalThis.fetch
  try {
    const { begin, runEffects } = harness.react
    const { useScanner } = harness.hook
    const accepted: unknown[] = []
    const onCheckedIn = (value: unknown) => accepted.push(value)
    const render = function RenderScanner(event = 'Event A', rows = [attendee], displayedEvent = event) {
      begin()
      const result = useScanner({ adminKey: 'synthetic-key', selectedEvent: event, eventName: displayedEvent, attendees: rows, onCheckedIn })
      runEffects()
      return result
    }
    let scanner = render()
    // Await the runtime camera test module so the preload effect has settled.
    const qr = await import(pathToFileURL(path.join(harness.dir, 'qr.js')).href)
    await new Promise<void>(resolve => setImmediate(resolve))
    await scanner.startScanner()
    const pending: ((response: Response) => void)[] = []
    globalThis.fetch = async () => new Promise<Response>(resolve => pending.push(resolve))
    const scan = qr.decode('synthetic-token')
    await new Promise<void>(resolve => setImmediate(resolve))
    assert.equal(pending.length, 1)
    scanner.clearResult() // Event picker invalidates requests synchronously.
    render('Event B')
    scanner = render('Event A')
    pending.shift()!(Response.json({ record }))
    await scan
    assert.deepEqual(accepted, [])
    assert.equal(render().scanResult, null)

    await scanner.startScanner()
    const oldRegistrationScan = qr.decode('synthetic-token')
    await new Promise<void>(resolve => setImmediate(resolve))
    const replacement = { ...attendee, registration_timestamp: stampB, extra_people: 3 }
    render('Event A', [replacement])
    assert.equal(pending.length, 1)
    pending.shift()!(Response.json({ record }))
    await oldRegistrationScan
    assert.deepEqual(accepted, [])
    assert.equal(render('Event A', [replacement]).scanResult, null)

    scanner = render('Event A', [replacement])
    await scanner.startScanner()
    const currentScan = qr.decode('synthetic-token')
    await new Promise<void>(resolve => setImmediate(resolve))
    assert.equal(pending.length, 1)
    const currentRecord = { ...record, registration_timestamp: stampB }
    pending.shift()!(Response.json({ record: currentRecord, already_checked_in: false }))
    await currentScan
    assert.deepEqual(accepted, [currentRecord])
    scanner = render('Event A', [replacement])
    assert.equal(scanner.scanResult.kind, 'checked_in')
    assert.equal(scanner.scanResult.extraPeople, 3)
    scanner.clearResult()
    scanner = render('Event B', [replacement], 'Event A')
    await scanner.startScanner()
    await qr.decode('synthetic-token')
    assert.equal(pending.length, 0, 'No action uses rows from a different displayed event')
    assert.equal(render('Event B', [replacement], 'Event A').scanResult, null)
  } finally {
    globalThis.fetch = previousFetch
    harness.react.cleanup()
    fs.rmSync(harness.dir, { recursive: true, force: true })
  }
})
