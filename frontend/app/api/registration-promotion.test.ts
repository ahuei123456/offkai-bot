import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import { NextRequest } from 'next/server.js'

test('actual promotion route requires organizer auth, preserves identity and never retries an uncertain commit', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.promotion-route-'))
  const previousFetch = globalThis.fetch
  const previousKey = process.env.ADMIN_KEY
  const previousBotUrl = process.env.BOT_ADMIN_URL
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    function compile(source: string, dest: string) {
      fs.mkdirSync(dest, { recursive: true })
      for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
        if (entry.isDirectory()) { compile(path.join(source, entry.name), path.join(dest, entry.name)); continue }
        if (!entry.name.endsWith('.ts') || entry.name.endsWith('.test.ts')) continue
        const code = ts.transpileModule(fs.readFileSync(path.join(source, entry.name), 'utf8'), {
          compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
        }).outputText.replace(/(from\s+['"]|import\(['"])(\.[^'"]+)(['"])/g, '$1$2.js$3')
          .replaceAll("'next/server'", "'next/server.js'")
        fs.writeFileSync(path.join(dest, entry.name.replace(/\.ts$/, '.js')), code)
      }
    }
    compile('app/api', path.join(dir, 'api'))
    const { POST } = await import(pathToFileURL(path.join(dir, 'api/registration/promote/route.js')).href)
    process.env.ADMIN_KEY = 'synthetic-admin'
    process.env.BOT_ADMIN_URL = 'http://synthetic-bot.invalid'
    const body = { event_name: 'Test event', user_id: '191524132624531458', registration_timestamp: '2026-10-01T00:00:00.123456Z' }
    const request = (key = 'synthetic-admin', payload: unknown = body) => new NextRequest(`http://localhost/api/registration/promote?key=${key}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    const posts: { url: string; init: RequestInit }[] = []
    globalThis.fetch = async (url, init) => {
      posts.push({ url: String(url), init: init! })
      return Response.json({ promoted: true, warnings: ['DM unavailable'] })
    }
    assert.equal((await POST(request('user-token'))).status, 401)
    assert.equal((await POST(request('synthetic-admin', { ...body, user_id: 123 }))).status, 400)
    assert.equal(posts.length, 0)
    const success = await POST(request())
    assert.equal(success.status, 200)
    assert.deepEqual(await success.json(), { promoted: true, warnings: ['DM unavailable'] })
    assert.equal(posts.length, 1)
    assert.equal(posts[0].url, 'http://synthetic-bot.invalid/registrations/promote')
    assert.equal(new Headers(posts[0].init.headers).get('authorization'), 'Bearer synthetic-admin')
    assert.deepEqual(JSON.parse(posts[0].init.body as string), { ...body, registration_timestamp: '2026-10-01T00:00:00.123Z' })
    let attempts = 0
    globalThis.fetch = async () => { attempts++; throw new Error('Response lost after commit') }
    const uncertain = await POST(request())
    assert.equal(uncertain.status, 502)
    assert.deepEqual(await uncertain.json(), { error: 'promotion_unconfirmed' })
    assert.equal(attempts, 1)
  } finally {
    globalThis.fetch = previousFetch
    if (previousKey === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = previousKey
    if (previousBotUrl === undefined) delete process.env.BOT_ADMIN_URL; else process.env.BOT_ADMIN_URL = previousBotUrl
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('actual up-arrow requires confirmation, blocks overlapping clicks and reports stale registrations', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.promotion-control-'))
  const previousWindow = globalThis.window
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    fs.writeFileSync(path.join(dir, 'react.js'), `const states=[],refs=[];let index=0,refIndex=0;
      export function begin(){index=0;refIndex=0;}
      export function useState(initial){const key=index++;if(!(key in states))states[key]=initial;
        return [states[key],value=>states[key]=value];}
      export function useRef(initial){return refs[refIndex++]??=( {current:initial} );}`)
    fs.writeFileSync(path.join(dir, 'i18n.js'), `export function useT(){return {t:{promoteUser:'Promote',
      confirmPromote:name=>'Promote '+name+' even if full; fresh 72-hour choice',
      promotionRegistrationChanged:'Registration changed',promotionNotStarted:'Not promoted',promotionError:'Unconfirmed'}};}`)
    const code = ts.transpileModule(fs.readFileSync('app/components/admin/PromoteRegistration.tsx', 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText.replaceAll("from 'react'", "from './react.js'").replaceAll("from '../../lib/i18n'", "from './i18n.js'")
    fs.writeFileSync(path.join(dir, 'control.js'), code)
    const { begin } = await import(pathToFileURL(path.join(dir, 'react.js')).href)
    const { PromoteRegistration } = await import(pathToFileURL(path.join(dir, 'control.js')).href)
    const attendee = { user_id: '191524132624531458', username: 'Synthetic', status: 'waitlist',
      registration_timestamp: '2026-10-01T00:00:00.000Z' }
    let confirmed = false
    globalThis.window = { confirm: () => confirmed } as unknown as Window & typeof globalThis
    const calls: unknown[] = []
    let complete!: (ok: boolean) => void
    const onPromote = async (...args: unknown[]) => { calls.push(args); return new Promise<boolean>(resolve => { complete = resolve }) }
    const render = (action = onPromote, status = 'waitlist') => {
      begin(); return PromoteRegistration({ attendee: { ...attendee, status }, onPromote: action })
    }
    let tree = render()
    const click = tree.props.children[0].props.onClick
    await click()
    assert.deepEqual(calls, [])
    confirmed = true
    const pending = click()
    await click()
    assert.deepEqual(calls, [[attendee.user_id, attendee.registration_timestamp]])
    assert.equal(render().props.children[0].props.disabled, true)
    complete(true)
    await pending
    tree = render(async () => { throw new Error('registration_changed') })
    await tree.props.children[0].props.onClick()
    tree = render()
    assert.equal(tree.props.children[1].props.role, 'alert')
    assert.equal(tree.props.children[1].props.children, 'Registration changed')
    tree = render(onPromote, 'attending')
    assert.equal(tree.props.children[0].props.disabled, true)
    await tree.props.children[0].props.onClick()
    assert.equal(calls.length, 1)
  } finally {
    if (previousWindow === undefined) delete (globalThis as { window?: Window }).window; else globalThis.window = previousWindow
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
