import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const tick = () => new Promise<void>(resolve => setImmediate(resolve))

test('payment event switch rejects stale actions and ignores delayed polls from the previous event', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.payment-hook-test-'))
  const previousFetch = globalThis.fetch
  const originalInterval = globalThis.setInterval
  const timers: ReturnType<typeof setInterval>[] = []
  const polls: (() => void)[] = []
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    // Stateful hook harness: run the real callbacks/effects without a DOM library.
    fs.writeFileSync(path.join(dir, 'react.js'), `
      const states = []; const refs = []; let index = 0; let refIndex = 0; let effects = [];
      export function begin(seed = {}, event) { index = 0; refIndex = 0; effects = [];
        for (const [key, value] of Object.entries(seed)) states[Number(key)] = value;
        if (event !== undefined) refs[0] = { current: event }; }
      export function useState(initial) { const key = index++; if (!(key in states)) states[key] = initial;
        return [states[key], value => { states[key] = typeof value === 'function' ? value(states[key]) : value; }]; }
      export function useRef(initial) { const key = refIndex++; return refs[key] ??= { current: initial }; }
      export function useCallback(fn) { return fn; }
      export function useEffect(fn) { effects.push(fn); }
      export function runEffects() { for (const fn of effects) fn(); }
    `)
    const source = fs.readFileSync(path.join(process.cwd(), 'app/hooks/useAdminData.ts'), 'utf8')
    const code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    }).outputText.replaceAll("from 'react'", "from './react.js'")
    fs.writeFileSync(path.join(dir, 'hook.js'), code)
    const { begin, runEffects } = await import(pathToFileURL(path.join(dir, 'react.js')).href)
    const { useAdminData } = await import(pathToFileURL(path.join(dir, 'hook.js')).href)
    const uid = '191524132624531458'
    const attendee = { user_id: uid, username: 'Synthetic', display_name: null, extra_people: 0, extras_names: [],
      drinks: [], status: 'attending', payment: { paid: false, proof: null } }
    const posts: { event_name: string; user_id: string; paid: boolean }[] = []
    globalThis.fetch = async (_url, options) => {
      if (options?.method === 'POST') {
        posts.push(JSON.parse(options.body as string))
        return new Response('{}', { status: 200 })
      }
      return Response.json({ event_name: 'Event A', attendees: [attendee] })
    }
    begin({ 0: 'synthetic-key', 1: true, 4: 'Event A', 6: 'Event A', 7: [attendee] }, 'Event A')
    const initial = useAdminData()
    initial.changeEvent('Event B')
    begin()
    const loading = useAdminData()
    assert.equal(await loading.updatePayment(uid, true), false)
    assert.equal(await loading.removeRegistration(uid), false)
    assert.deepEqual(posts, [])
    loading.changeEvent('Event A')
    begin()
    const loaded = useAdminData()
    assert.equal(await loaded.updatePayment(uid, true), true)
    assert.deepEqual(posts, [{ event_name: 'Event A', user_id: uid, paid: true }])
    // A's initial load and 10-second poll both remain pending during A → B.
    const pending: { event: string; resolve: (value: Response) => void }[] = []
    globalThis.fetch = async (url, options) => {
      if (options?.method === 'POST') { posts.push(JSON.parse(options.body as string)); return Response.json({}) }
      const parsed = new URL(String(url), 'http://localhost')
      if (parsed.pathname === '/api/checkin') return Response.json([])
      return new Promise<Response>(resolve => pending.push({ event: parsed.searchParams.get('event')!, resolve }))
    }
    globalThis.setInterval = ((callback: () => void) => {
      polls.push(callback)
      const timer = originalInterval(() => {}, 100_000)
      timers.push(timer)
      return timer
    }) as typeof setInterval
    begin()
    const beforeSwitch = useAdminData()
    runEffects()
    polls[0]()
    assert.equal(pending.filter(p => p.event === 'Event A').length, 2)
    beforeSwitch.changeEvent('Event B')
    begin()
    const duringSwitch = useAdminData()
    runEffects()
    assert.equal(await duringSwitch.updatePayment(uid, true), false)
    const next = pending.find(p => p.event === 'Event B')!
    next.resolve(Response.json({ event_name: 'Event B', attendees: [{ ...attendee, payment: { paid: true, proof: null } }] }))
    await tick()
    for (const previous of pending.filter(p => p.event === 'Event A')) {
      previous.resolve(Response.json({ event_name: 'Event A', attendees: [attendee] }))
    }
    await tick()
    begin()
    const settled = useAdminData()
    assert.equal(settled.eventName, 'Event B')
    assert.equal(settled.attendees[0].payment.paid, true)
    const previousPostCount = posts.length
    // Even a callback retained from the old render cannot mutate the new event.
    assert.equal(await beforeSwitch.updatePayment(uid, true), false)
    assert.equal(posts.length, previousPostCount)
  } finally {
    globalThis.fetch = previousFetch
    globalThis.setInterval = originalInterval
    for (const timer of timers) clearInterval(timer)
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
