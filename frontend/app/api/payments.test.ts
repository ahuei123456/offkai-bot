import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import sharp from 'sharp'
import { NextRequest } from 'next/server.js'

// Native Node runner plus the repository's existing compiler: compile route
// imports into an isolated module tree so actual handlers can run without Next.
// No test-only behavior is added to production handlers.
function compileRoutes() {
  const output = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.payment-tests-'))
  fs.writeFileSync(path.join(output, 'package.json'), '{"type":"module"}')
  const apiDir = path.join(process.cwd(), 'app', 'api')
  function compile(source: string, dest: string) {
    fs.mkdirSync(dest, { recursive: true })
    for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
      if (entry.isDirectory()) { compile(path.join(source, entry.name), path.join(dest, entry.name)); continue }
      if (!entry.name.endsWith('.ts') || entry.name.endsWith('.test.ts')) continue
      let code = ts.transpileModule(fs.readFileSync(path.join(source, entry.name), 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
      }).outputText
      code = code.replace(/(from\s+['"]|import\(['"])(\.[^'"]+)(['"])/g, '$1$2.js$3')
        .replaceAll("'next/server'", "'next/server.js'")
      fs.writeFileSync(path.join(dest, entry.name.replace(/\.ts$/, '.js')), code)
    }
  }
  compile(apiDir, path.join(output, 'api'))
  let instrumentation = ts.transpileModule(fs.readFileSync(path.join(process.cwd(), 'instrumentation.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  instrumentation = instrumentation.replaceAll('./app/api/payments', './api/payments.js').replaceAll('./app/api/db', './api/db.js')
  fs.writeFileSync(path.join(output, 'instrumentation.js'), instrumentation)
  return output
}

const uid = '191524132624531458'
const otherUid = '191524132624531459'
const eventNames = ['Synthetic Confirmed', 'Synthetic Waitlist']
function signedToken(userId: string, eventName: string) {
  const payload = Buffer.from(`${userId}:${eventName}`).toString('base64url')
  const sig = crypto.createHmac('sha256', 'synthetic-test-key').update(payload).digest('hex').slice(0, 16)
  return `v2.${payload}.${sig}`
}
function request(url: string, body?: unknown) {
  return new NextRequest(`http://localhost${url}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
}

test('synthetic confirmed and waitlist payment flow, isolation, auth, image processing and retention', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'offkai-payment-data-'))
  const modules = compileRoutes()
  const previousDir = process.env.BOT_DATA_DIR
  const previousKey = process.env.ADMIN_KEY
  process.env.BOT_DATA_DIR = dataDir
  process.env.ADMIN_KEY = 'synthetic-test-key'
  process.env.MOCK_MODE = 'false'
  try {
    const start = new Date(Date.now() + 24 * 3600 * 1000).toISOString()
    const events = eventNames.map(event_name => ({
      event_name, event_datetime: start, archived: false, open: true,
      signup_form: { fields: ['payment_method', 'no_show'], payment_methods: { PayNow: 'Synthetic organizer instructions' } },
    }))
    const attendee = { user_id: uid, username: 'Synthetic', display_name: 'Recorded name', extra_people: 1,
      extras_names: ['Guest'], drinks: [], payment_method: 'PayNow', no_show_agreed: true }
    fs.writeFileSync(path.join(dataDir, 'events.json'), JSON.stringify(events))
    fs.writeFileSync(path.join(dataDir, 'responses.json'), JSON.stringify({
      [eventNames[0]]: { attendees: [attendee], waitlist: [] },
      [eventNames[1]]: { attendees: [], waitlist: [attendee] },
    }))
    if (process.env.OFFKAI_SYNTHETIC_OUTPUT) {
      for (const filename of ['events.json', 'responses.json']) {
        fs.copyFileSync(path.join(process.env.OFFKAI_SYNTHETIC_OUTPUT, filename), path.join(dataDir, filename))
      }
      const replies = JSON.parse(fs.readFileSync(path.join(process.env.OFFKAI_SYNTHETIC_OUTPUT, 'replies.json'), 'utf8'))
      for (const name of eventNames) {
        assert.equal(replies[name].token, signedToken(uid, name))
        assert.ok(replies[name].reply.includes('Synthetic organizer instructions'))
        assert.ok(replies[name].reply.includes(signedToken(uid, name)))
      }
    }
    const originalResponses = fs.readFileSync(path.join(dataDir, 'responses.json'), 'utf8')
    const importModule = (file: string) => import(pathToFileURL(path.join(modules, 'api', file)).href)
    const proofRoute = await importModule('payment-proof/route.js')
    const paidRoute = await importModule('payment/route.js')
    const attendeeRoute = await importModule('attendee/route.js')
    const attendeesRoute = await importModule('attendees/route.js')
    const payments = await importModule('payments.js')
    const original = await sharp({ create: { width: 1600, height: 800, channels: 3, background: 'red' } })
      .jpeg().withMetadata({ orientation: 6 }).toBuffer()
    const upload = (token: string, bytes: Buffer = original, mime = 'image/jpeg') => {
      const form = new FormData()
      form.set('token', token)
      form.set('image', new Blob([new Uint8Array(bytes)], { type: mime }), 'untrusted-name.jpg')
      return proofRoute.POST(new NextRequest('http://localhost/api/payment-proof', { method: 'POST', body: form }))
    }
    assert.equal((await upload('bad-token')).status, 401)
    // Chunked body with an oversized ignored part must stop before token parsing.
    let consumed = 0
    let cancelled = false
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) { consumed += 64 * 1024; controller.enqueue(new Uint8Array(64 * 1024)) },
      cancel() { cancelled = true },
    })
    const oversizedRequest = new NextRequest('http://localhost/api/payment-proof', {
      method: 'POST', headers: { 'Content-Type': 'multipart/form-data; boundary=synthetic' },
      body: stream, duplex: 'half',
    } as RequestInit)
    assert.equal(oversizedRequest.headers.get('content-length'), null)
    assert.equal((await proofRoute.POST(oversizedRequest)).status, 413)
    assert.equal(cancelled, true)
    assert.ok(consumed <= 10 * 1024 * 1024 + 3 * 64 * 1024)
    assert.equal((await upload(signedToken(otherUid, eventNames[0]))).status, 404)
    assert.equal((await upload(signedToken(uid, eventNames[0]), Buffer.from('not an image'))).status, 400)
    assert.equal((await upload(signedToken(uid, eventNames[0]), Buffer.alloc(10 * 1024 * 1024 + 1))).status, 413)
    assert.equal((await proofRoute.GET(request('/api/payment-proof'))).status, 401)
    for (let i = 0; i < eventNames.length; i++) {
      const name = eventNames[i]
      const token = signedToken(uid, name)
      // Marking paid without an image works for either registration status.
      let paid = await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: name, user_id: uid, paid: true }))
      assert.equal(paid.status, 200)
      assert.equal((await paid.json()).payment.proof, null)
      const uploaded = await upload(token)
      assert.equal(uploaded.status, 200)
      assert.equal((await uploaded.json()).payment.paid, true)
      const read = await proofRoute.GET(request('/api/payment-proof?token=' + token))
      assert.equal(read.status, 200)
      assert.equal(read.headers.get('cache-control'), 'private, no-store')
      const metadata = await sharp(Buffer.from(await read.arrayBuffer())).metadata()
      assert.equal(metadata.format, 'webp')
      assert.ok(metadata.width! <= 1080)
      assert.equal(metadata.orientation, undefined)
      assert.equal(metadata.exif, undefined)
      const adminRead = await proofRoute.GET(request(`/api/payment-proof?key=synthetic-test-key&event=${encodeURIComponent(name)}&user_id=${uid}`))
      assert.equal(adminRead.status, 200)
      const pass = await (await attendeeRoute.GET(request('/api/attendee?token=' + token))).json()
      assert.equal(pass.attendee.status, i === 0 ? 'attending' : 'waitlist')
      assert.equal(pass.attendee.payment_instructions, 'Synthetic organizer instructions')
      assert.equal(pass.attendee.payment_method, 'PayNow')
      assert.equal(pass.attendee.no_show_agreed, true)
      assert.equal(pass.attendee.payment.paid, true)
      paid = await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: name, user_id: uid, paid: false }))
      assert.equal((await paid.json()).payment.paid, false)
      // Replacing a proof preserves unpaid status and removes the old image.
      assert.equal((await (await upload(token)).json()).payment.paid, false)
      await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: name, user_id: uid, paid: true }))
      const list = await (await attendeesRoute.GET(request(`/api/attendees?key=synthetic-test-key&event=${encodeURIComponent(name)}`))).json()
      assert.equal(list.attendees[0].user_id, uid)
      assert.equal(list.attendees[0].payment.paid, true)
    }
    assert.equal(fs.readdirSync(path.join(dataDir, 'payment-proofs')).length, 2)
    assert.notEqual(payments.getPayment(eventNames[0], uid).proof.filename, payments.getPayment(eventNames[1], uid).proof.filename)
    assert.equal((await proofRoute.GET(request('/api/payment-proof?token=' + signedToken(otherUid, eventNames[0])))).status, 404)
    assert.equal((await paidRoute.POST(request('/api/payment?key=wrong', { event_name: eventNames[0], user_id: uid, paid: true }))).status, 401)
    assert.equal(fs.readFileSync(path.join(dataDir, 'responses.json'), 'utf8'), originalResponses)
    assert.equal(fs.existsSync(path.join(dataDir, 'checkins.json')), false)
    // Expired metadata remains authoritative even after events disappear.
    const file = path.join(dataDir, 'payments.json')
    const state = JSON.parse(fs.readFileSync(file, 'utf8'))
    for (const name of eventNames) state[name][uid].proof.expires_at = '2000-01-01T00:00:00.000Z'
    fs.writeFileSync(file, JSON.stringify(state))
    assert.equal((await proofRoute.GET(request('/api/payment-proof?token=' + signedToken(uid, eventNames[0])))).status, 404)
    fs.writeFileSync(path.join(dataDir, 'events.json'), '[]')
    process.env.NEXT_RUNTIME = 'nodejs'
    const instrumentation = await import(pathToFileURL(path.join(modules, 'instrumentation.js')).href)
    await instrumentation.register()
    const cleanupState = globalThis as typeof globalThis & { paymentCleanup?: ReturnType<typeof setInterval> }
    const timer = cleanupState.paymentCleanup
    assert.ok(timer)
    await instrumentation.register()
    assert.equal(cleanupState.paymentCleanup, timer)
    clearInterval(timer)
    delete cleanupState.paymentCleanup
    payments.cleanupProofs([])
    assert.equal(fs.readdirSync(path.join(dataDir, 'payment-proofs')).length, 0)
    assert.equal(payments.getPayment(eventNames[0], uid).paid, true)
    assert.equal(payments.getPayment(eventNames[0], uid).proof, null)
    events[0].event_datetime = '2000-01-01T00:00:00Z'
    fs.writeFileSync(path.join(dataDir, 'events.json'), JSON.stringify(events))
    assert.equal((await upload(signedToken(uid, eventNames[0]))).status, 410)
    assert.equal(payments.proofExpiry('2027-01-31T10:00:00Z'), '2027-04-30T13:00:00.000Z')
    assert.equal(payments.proofExpiry('2026-11-30T14:00:00Z'), '2027-02-28T17:00:00.000Z')
    const small = await sharp({ create: { width: 100, height: 50, channels: 3, background: 'blue' } }).png().toBuffer()
    assert.equal((await sharp(await payments.normalizeProof(small)).metadata()).width, 100)
    for (const format of ['webp', 'gif'] as const) {
      const image = await sharp(small).toFormat(format).toBuffer()
      assert.equal((await sharp(await payments.normalizeProof(image)).metadata()).format, 'webp')
    }
    const tooManyPixels = await sharp({ create: { width: 8000, height: 6000, channels: 3, background: 'white' } })
      .png().toBuffer()
    await assert.rejects(() => payments.normalizeProof(tooManyPixels))
  } finally {
    if (previousDir === undefined) delete process.env.BOT_DATA_DIR; else process.env.BOT_DATA_DIR = previousDir
    if (previousKey === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = previousKey
    fs.rmSync(modules, { recursive: true, force: true })
    fs.rmSync(dataDir, { recursive: true, force: true })
  }
})
