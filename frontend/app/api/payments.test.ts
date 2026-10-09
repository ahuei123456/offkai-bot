import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { createServer } from 'node:http'
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
function request(url: string, body?: unknown, headers: Record<string, string> = {}) {
  if (url.startsWith('/api/payment?') && body && typeof body === 'object' && !Object.hasOwn(body, 'registration_timestamp')) {
    const input = body as { event_name: string; user_id: string }
    const data = JSON.parse(fs.readFileSync(path.join(process.env.BOT_DATA_DIR!, 'responses.json'), 'utf8').replace(/(\"user_id\"\s*:\s*)(\d+)/g, '$1\"$2\"'))
    const rows = data[input.event_name]
    const attendee = [...(rows?.attendees || []), ...(rows?.waitlist || [])].find(a => a.user_id === input.user_id)
    body = { ...input, registration_timestamp: attendee?.timestamp }
  }
  return new NextRequest(`http://localhost${url}`, body === undefined ? { headers } : {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body),
  })
}

test('synthetic confirmed and waitlist payment flow, isolation, auth, image processing and retention', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'offkai-payment-data-'))
  const modules = compileRoutes()
  const previousDir = process.env.BOT_DATA_DIR
  const previousKey = process.env.ADMIN_KEY
  const previousBotUrl = process.env.BOT_ADMIN_URL
  const notifications: unknown[] = []
  let failNotification = false
  const bot = createServer(async (req, res) => {
    assert.equal(req.url, '/payments/confirm')
    assert.equal(req.headers.authorization, 'Bearer synthetic-test-key')
    let body = ''
    for await (const chunk of req) body += chunk
    const payload = JSON.parse(body)
    // The state must already be persisted when the callback arrives.
    const saved = JSON.parse(fs.readFileSync(path.join(dataDir, 'payments.json'), 'utf8'))
    assert.equal(saved[payload.event_name][payload.user_id].paid, true)
    notifications.push(payload)
    res.writeHead(failNotification ? 502 : 200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(failNotification ? { error: 'dm_failed' } : { sent: true }))
  })
  await new Promise<void>(resolve => bot.listen(0, '127.0.0.1', resolve))
  const botAddress = bot.address()
  assert.ok(botAddress && typeof botAddress !== 'string')
  process.env.BOT_ADMIN_URL = `http://127.0.0.1:${botAddress.port}`
  process.env.BOT_DATA_DIR = dataDir
  process.env.ADMIN_KEY = 'synthetic-test-key'
  process.env.MOCK_MODE = 'false'
  try {
    const start = new Date(Date.now() + 24 * 3600 * 1000).toISOString()
    const events = eventNames.map(event_name => ({
      event_name, event_datetime: start, archived: false, open: true,
      signup_form: { fields: ['payment_method', 'no_show'], payment_methods: { PayNow: 'Synthetic organizer instructions' },
        ...(event_name === eventNames[0] ? { payment_instructions_jp: { PayNow: '主催者の支払い案内' } } : {}) },
    }))
    const registrationTime = new Date(Date.now() - 3600 * 1000).toISOString()
    const attendee = { timestamp: registrationTime, user_id: uid, username: 'Synthetic', display_name: 'Recorded name', extra_people: 1,
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
      const count = notifications.length
      await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: name, user_id: uid, paid: true }))
      assert.equal(notifications.length, count, 'Repeated Mark paid must not send another DM')
      const uploaded = await upload(token)
      assert.equal(uploaded.status, 200)
      const uploadedData = await uploaded.json()
      assert.equal(uploadedData.payment.paid, true)
      assert.equal(uploadedData.replaced, false)
      const read = await proofRoute.GET(request('/api/payment-proof?token=' + token))
      assert.equal(read.status, 200)
      assert.equal(read.headers.get('cache-control'), 'private, no-store')
      const metadata = await sharp(Buffer.from(await read.arrayBuffer())).metadata()
      assert.equal(metadata.format, 'webp')
      assert.ok(metadata.width! <= 1080)
      assert.equal(metadata.orientation, undefined)
      assert.equal(metadata.exif, undefined)
      const adminRead = await proofRoute.GET(request(`/api/payment-proof?event=${encodeURIComponent(name)}&user_id=${uid}&registration_timestamp=${encodeURIComponent(registrationTime)}&proof_filename=${uploadedData.payment.proof.filename}`, undefined, { Authorization: 'Bearer synthetic-test-key' }))
      assert.equal(adminRead.status, 200)
      const pass = await (await attendeeRoute.GET(request('/api/attendee?token=' + token))).json()
      assert.equal(pass.attendee.status, i === 0 ? 'attending' : 'waitlist')
      assert.equal(pass.attendee.payment_instructions, 'Synthetic organizer instructions')
      assert.equal(pass.attendee.payment_instructions_jp, i === 0 ? '主催者の支払い案内' : null)
      assert.equal(pass.attendee.payment_method, 'PayNow')
      assert.equal(pass.attendee.no_show_agreed, true)
      assert.equal(pass.attendee.payment.paid, true)
      paid = await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: name, user_id: uid, paid: false }))
      assert.equal((await paid.json()).payment.paid, false)
      // Replacing a proof preserves unpaid status and removes the old image.
      const replacement = await (await upload(token)).json()
      assert.equal(replacement.payment.paid, false)
      assert.equal(replacement.replaced, true)
      await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: name, user_id: uid, paid: true }))
      const list = await (await attendeesRoute.GET(request(`/api/attendees?key=synthetic-test-key&event=${encodeURIComponent(name)}`))).json()
      assert.equal(list.attendees[0].user_id, uid)
      assert.equal(list.attendees[0].payment.paid, true)
    }
    assert.equal(notifications.length, 4)
    failNotification = true
    await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: eventNames[0], user_id: uid, paid: false }))
    const failedDm = await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: eventNames[0], user_id: uid, paid: true }))
    assert.equal(failedDm.status, 200)
    const persisted = await failedDm.json()
    assert.equal(persisted.payment.paid, true)
    assert.match(persisted.warning, /confirmation DM/)
    assert.equal(fs.readdirSync(path.join(dataDir, 'payment-proofs')).length, 2)
    assert.notEqual(payments.getPayment(eventNames[0], uid, registrationTime).proof.filename, payments.getPayment(eventNames[1], uid, registrationTime).proof.filename)
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
    assert.equal(payments.getPayment(eventNames[0], uid, registrationTime).paid, true)
    assert.equal(payments.getPayment(eventNames[0], uid, registrationTime).proof, null)
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
    await new Promise<void>((resolve, reject) => bot.close(error => error ? reject(error) : resolve()))
    if (previousBotUrl === undefined) delete process.env.BOT_ADMIN_URL; else process.env.BOT_ADMIN_URL = previousBotUrl
    if (previousDir === undefined) delete process.env.BOT_DATA_DIR; else process.env.BOT_DATA_DIR = previousDir
    if (previousKey === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = previousKey
    fs.rmSync(modules, { recursive: true, force: true })
    fs.rmSync(dataDir, { recursive: true, force: true })
  }
})


test('payment gating, registration lifetime, promotion, legacy migration and corrupt display storage', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'offkai-review-payment-'))
  const modules = compileRoutes()
  const previousDir = process.env.BOT_DATA_DIR
  const previousKey = process.env.ADMIN_KEY
  process.env.BOT_DATA_DIR = dataDir
  process.env.ADMIN_KEY = 'synthetic-test-key'
  process.env.MOCK_MODE = 'false'
  try {
    const eventName = 'Registration lifetime'
    const start = new Date(Date.now() + 86400000).toISOString()
    const originalTime = new Date(Date.now() - 7200000).toISOString()
    const replacementTime = new Date(Date.now() - 3600000).toISOString()
    const events = [{ event_name: eventName, event_datetime: start, archived: false, open: true,
      signup_form: { fields: ['payment_method'], payment_methods: { PayNow: 'Pay the organizer' } } },
      { event_name: 'No prepayment', event_datetime: start, archived: false, open: true }]
    const attendee = { timestamp: originalTime, user_id: uid, username: 'Synthetic', extra_people: 0,
      payment_method: 'PayNow', behavior_confirmed: true, arrival_confirmed: true }
    const responseFile = path.join(dataDir, 'responses.json')
    const paymentFile = path.join(dataDir, 'payments.json')
    const writeResponses = (timestamp: string, waitlisted = false) => fs.writeFileSync(responseFile, JSON.stringify({
      [eventName]: { attendees: waitlisted ? [] : [{ ...attendee, timestamp }], waitlist: waitlisted ? [{ ...attendee, timestamp }] : [] },
      'No prepayment': { attendees: [attendee], waitlist: [] },
    }))
    fs.writeFileSync(path.join(dataDir, 'events.json'), JSON.stringify(events))
    writeResponses(originalTime, true)
    const importModule = (file: string) => import(pathToFileURL(path.join(modules, 'api', file)).href)
    const payments = await importModule('payments.js')
    const proofRoute = await importModule('payment-proof/route.js')
    const paidRoute = await importModule('payment/route.js')
    const attendeeRoute = await importModule('attendee/route.js')
    const attendeesRoute = await importModule('attendees/route.js')
    const token = signedToken(uid, eventName)
    const image = await sharp({ create: { width: 20, height: 20, channels: 3, background: 'blue' } }).png().toBuffer()
    const proof = await payments.saveProof(eventName, uid, start, image, originalTime)
    payments.setPaid(eventName, uid, true, originalTime)
    const oldImage = path.join(dataDir, 'payment-proofs', proof.proof.filename)
    // Promotion changes only status; the registration and its payment survive.
    writeResponses(originalTime)
    let pass = await (await attendeeRoute.GET(request('/api/attendee?token=' + token))).json()
    assert.equal(pass.attendee.status, 'attending')
    assert.equal(pass.attendee.payment.paid, true)
    assert.equal(pass.attendee.payment.proof.filename, proof.proof.filename)
    assert.equal(payments.getPayment(eventName, uid, originalTime.replace('Z', '+00:00')).paid, true)
    // Rejoining, even under a reused event name, must start unpaid without old proof.
    writeResponses(replacementTime)
    pass = await (await attendeeRoute.GET(request('/api/attendee?token=' + token))).json()
    assert.equal(pass.attendee.payment.paid, false)
    assert.equal(pass.attendee.payment.proof, null)
    assert.equal((await proofRoute.GET(request('/api/payment-proof?token=' + token))).status, 404)
    const fresh = await payments.saveProof(eventName, uid, start, image, replacementTime)
    assert.equal(fresh.paid, false)
    assert.equal(fs.existsSync(oldImage), false)
    // Actual asynchronous image work cannot attach an old upload to a new signup.
    const pending = payments.saveProof(eventName, uid, start, image, replacementTime)
    writeResponses(new Date().toISOString())
    await assert.rejects(pending, /Registration changed/)
    // Existing unbound records migrate only when their evidence belongs to this signup.
    const legacy = { paid: true, paid_at: replacementTime, proof: { ...proof.proof, uploaded_at: replacementTime } }
    fs.writeFileSync(paymentFile, JSON.stringify({ [eventName]: { [uid]: legacy } }))
    assert.equal(payments.getPayment(eventName, uid, originalTime).paid, true)
    assert.equal(payments.getPayment(eventName, uid, new Date().toISOString()).paid, false)
    assert.equal(payments.getPayment(eventName, uid, new Date().toISOString()).proof, null)
    // One ledger read serves multiple attendees and waitlist entries in a poll.
    fs.writeFileSync(responseFile, JSON.stringify({ [eventName]: {
      attendees: [attendee, { ...attendee, user_id: otherUid }], waitlist: [{ ...attendee, user_id: '191524132624531460' }],
    }, 'No prepayment': { attendees: [attendee], waitlist: [] } }))
    let reads = 0
    const originalRead = fs.readFileSync
    fs.readFileSync = function (...args: Parameters<typeof fs.readFileSync>) {
      if (String(args[0]) === paymentFile) reads++
      return originalRead.apply(fs, args)
    } as typeof fs.readFileSync
    try {
      const listed = await (await attendeesRoute.GET(request('/api/attendees?key=synthetic-test-key&event=' + encodeURIComponent(eventName)))).json()
      assert.equal(listed.attendees.length, 3)
      assert.equal(reads, 1)
    } finally { fs.readFileSync = originalRead }
    // Broken payment storage leaves attendance usable and forbids ledger writes.
    fs.writeFileSync(paymentFile, '{broken')
    pass = await (await attendeeRoute.GET(request('/api/attendee?token=' + token))).json()
    assert.equal(pass.attendee.payment_unavailable, true)
    assert.equal(pass.attendee.payment, null)
    const listed = await (await attendeesRoute.GET(request('/api/attendees?key=synthetic-test-key&event=' + encodeURIComponent(eventName)))).json()
    assert.ok(listed.attendees.every((a: { payment_unavailable: boolean }) => a.payment_unavailable))
    assert.throws(() => payments.setPaid(eventName, uid, true, originalTime))
    assert.equal(fs.readFileSync(paymentFile, 'utf8'), '{broken')
    const freeToken = signedToken(uid, 'No prepayment')
    const free = await (await attendeeRoute.GET(request('/api/attendee?token=' + freeToken))).json()
    assert.equal(free.attendee.payment_enabled, false)
    assert.equal(free.attendee.payment_unavailable, false)
    assert.equal(free.attendee.payment, null)
    const form = new FormData()
    form.set('token', freeToken)
    form.set('image', new Blob([new Uint8Array(image)], { type: 'image/png' }), 'proof.png')
    assert.equal((await proofRoute.POST(new NextRequest('http://localhost/api/payment-proof', { method: 'POST', body: form }))).status, 404)
    assert.equal((await paidRoute.POST(request('/api/payment?key=synthetic-test-key', { event_name: 'No prepayment', user_id: uid, paid: true }))).status, 404)
    assert.equal(fs.readFileSync(paymentFile, 'utf8'), '{broken')
  } finally {
    if (previousDir === undefined) delete process.env.BOT_DATA_DIR; else process.env.BOT_DATA_DIR = previousDir
    if (previousKey === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = previousKey
    fs.rmSync(dataDir, { recursive: true, force: true })
    fs.rmSync(modules, { recursive: true, force: true })
  }
})


test('round-two stale paid actions, undated legacy binding, proof removal and upload error statuses', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'offkai-round-two-'))
  const modules = compileRoutes()
  const previousDir = process.env.BOT_DATA_DIR
  const previousKey = process.env.ADMIN_KEY
  const previousBotUrl = process.env.BOT_ADMIN_URL
  let notifications = 0
  const bot = createServer((_req, res) => { notifications++; res.end('{}') })
  await new Promise<void>(resolve => bot.listen(0, '127.0.0.1', resolve))
  const address = bot.address()
  assert.ok(address && typeof address !== 'string')
  process.env.BOT_DATA_DIR = dataDir
  process.env.ADMIN_KEY = 'synthetic-test-key'
  process.env.BOT_ADMIN_URL = `http://127.0.0.1:${address.port}`
  process.env.MOCK_MODE = 'false'
  try {
    const eventName = 'Round two'
    const start = new Date(Date.now() + 86400000).toISOString()
    const stampA = new Date(Date.now() - 7200000).toISOString()
    const stampB = new Date(Date.now() - 3600000).toISOString()
    const attendee = (user_id: string, timestamp = stampA) => ({ user_id, timestamp, username: 'Synthetic', extra_people: 0 })
    const responseFile = path.join(dataDir, 'responses.json')
    const paymentFile = path.join(dataDir, 'payments.json')
    const responses = (rows: unknown[], waitlist: unknown[] = []) => fs.writeFileSync(responseFile, JSON.stringify({
      [eventName]: { attendees: rows, waitlist },
    }))
    fs.writeFileSync(path.join(dataDir, 'events.json'), JSON.stringify([{ event_name: eventName, event_datetime: start,
      archived: false, open: true, signup_form: { fields: ['payment_method'], payment_methods: { Cash: 'Pay organizer' } } }]))
    responses([attendee(uid)])
    const load = (name: string) => import(pathToFileURL(path.join(modules, 'api', name)).href)
    const payments = await load('payments.js')
    const paidRoute = await load('payment/route.js')
    const proofRoute = await load('payment-proof/route.js')
    const listRoute = await load('attendees/route.js')
    // Grandfather undated legacy paid state once, without another notification.
    fs.writeFileSync(paymentFile, JSON.stringify({ [eventName]: { [uid]: { paid: true } } }))
    const listed = await (await listRoute.GET(request('/api/attendees?key=synthetic-test-key&event=' + encodeURIComponent(eventName)))).json()
    assert.equal(listed.attendees[0].payment.paid, true)
    assert.equal(listed.attendees[0].registration_timestamp, stampA)
    assert.equal(JSON.parse(fs.readFileSync(paymentFile, 'utf8'))[eventName][uid].registration_timestamp, stampA)
    assert.equal(notifications, 0)
    responses([attendee(uid, stampB)])
    assert.equal(payments.getPayment(eventName, uid, stampB).paid, false)
    const before = fs.readFileSync(paymentFile, 'utf8')
    const stale = await paidRoute.POST(request('/api/payment?key=synthetic-test-key', {
      event_name: eventName, user_id: uid, paid: true, registration_timestamp: stampA,
    }))
    assert.equal(stale.status, 409)
    assert.equal(fs.readFileSync(paymentFile, 'utf8'), before)
    assert.equal(notifications, 0)
    assert.equal((await paidRoute.POST(request('/api/payment?key=synthetic-test-key', {
      event_name: eventName, user_id: uid, paid: true, registration_timestamp: null,
    }))).status, 400)
    const cash = await paidRoute.POST(request('/api/payment?key=synthetic-test-key', {
      event_name: eventName, user_id: uid, paid: true, registration_timestamp: stampB.replace('Z', '+00:00'),
    }))
    assert.equal(cash.status, 200)
    assert.equal((await cash.json()).payment.proof, null)
    assert.equal(notifications, 1)
    const image = await sharp({ create: { width: 20, height: 20, channels: 3, background: 'blue' } }).png().toBuffer()
    const upload = (bytes = image) => {
      const form = new FormData()
      form.set('token', signedToken(uid, eventName))
      form.set('image', new Blob([new Uint8Array(bytes)], { type: 'image/png' }), 'proof.png')
      return proofRoute.POST(new NextRequest('http://localhost/api/payment-proof', { method: 'POST', body: form }))
    }
    assert.equal((await upload(Buffer.from('invalid'))).status, 400)
    assert.equal((await proofRoute.POST(new NextRequest('http://localhost/api/payment-proof', {
      method: 'POST', headers: { 'Content-Type': 'multipart/form-data; boundary=missing' }, body: 'malformed',
    }))).status, 400)
    // A real write failure is a server error, and the new image is rolled back.
    const originalRename = fs.renameSync
    fs.renameSync = ((from, to) => {
      if (String(to) === paymentFile) throw Object.assign(new Error('Denied'), { code: 'EACCES' })
      originalRename(from, to)
    }) as typeof fs.renameSync
    try { assert.equal((await upload()).status, 500) } finally { fs.renameSync = originalRename }
    assert.equal(fs.readdirSync(path.join(dataDir, 'payment-proofs')).length, 0)
    // Replace the canonical registration between initial resolve and post-image resolve.
    const originalRead = fs.readFileSync
    let registrationReads = 0
    fs.readFileSync = function (...args: Parameters<typeof fs.readFileSync>) {
      if (String(args[0]) === responseFile && ++registrationReads === 2) responses([attendee(uid)])
      return originalRead.apply(fs, args)
    } as typeof fs.readFileSync
    try { assert.equal((await upload()).status, 409) } finally { fs.readFileSync = originalRead }
    assert.equal(fs.readdirSync(path.join(dataDir, 'payment-proofs')).length, 0)
    responses([attendee(uid)], [attendee(otherUid)])
    const confirmed = await payments.saveProof(eventName, uid, start, image, stampA)
    const waiting = await payments.saveProof(eventName, otherUid, start, image, stampA)
    const imagePath = (record: { proof: { filename: string } }) => path.join(dataDir, 'payment-proofs', record.proof.filename)
    const adminUrl = `/api/payment-proof?event=${encodeURIComponent(eventName)}&user_id=${uid}&registration_timestamp=${encodeURIComponent(stampA)}&proof_filename=${confirmed.proof.filename}`
    assert.equal((await proofRoute.GET(request(adminUrl + '&key=synthetic-test-key'))).status, 401)
    assert.equal((await proofRoute.GET(request(adminUrl, undefined, { Authorization: 'Bearer synthetic-test-key' }))).status, 200)
    const replacedPreview = await payments.saveProof(eventName, uid, start, image, stampA)
    assert.equal((await proofRoute.GET(request(adminUrl, undefined, { Authorization: 'Bearer synthetic-test-key' }))).status, 409)
    const newPreview = adminUrl.replace(confirmed.proof.filename, replacedPreview.proof.filename)
    responses([attendee(uid, stampB)], [attendee(otherUid)])
    assert.equal((await proofRoute.GET(request(newPreview, undefined, { Authorization: 'Bearer synthetic-test-key' }))).status, 409)
    responses([attendee(uid)], [attendee(otherUid)])
    confirmed.proof = replacedPreview.proof
    // Promotion retains both images; either confirmed or waitlist withdrawal purges.
    responses([attendee(uid), attendee(otherUid)])
    payments.cleanupProofs([])
    assert.ok(fs.existsSync(imagePath(confirmed)) && fs.existsSync(imagePath(waiting)))
    responses([], [attendee(otherUid)])
    payments.cleanupProofs([])
    assert.equal(fs.existsSync(imagePath(confirmed)), false)
    assert.equal(fs.existsSync(imagePath(waiting)), true)
    const ledger = fs.readFileSync(paymentFile, 'utf8')
    fs.writeFileSync(responseFile, '{broken')
    assert.throws(() => payments.cleanupProofs([]))
    assert.equal(fs.readFileSync(paymentFile, 'utf8'), ledger)
    assert.equal(fs.existsSync(imagePath(waiting)), true)
    fs.writeFileSync(responseFile, JSON.stringify({ [eventName]: { attendees: [{ user_id: otherUid, timestamp: 42 }], waitlist: [] } }))
    assert.throws(() => payments.cleanupProofs([]))
    assert.equal(fs.existsSync(imagePath(waiting)), true)
    fs.unlinkSync(responseFile)
    assert.throws(() => payments.cleanupProofs([]))
    assert.equal(fs.existsSync(imagePath(waiting)), true)
    responses([])
    fs.renameSync = ((from, to) => {
      if (String(to) === paymentFile) throw new Error('Denied ledger update')
      originalRename(from, to)
    }) as typeof fs.renameSync
    try {
      assert.throws(() => payments.cleanupProofs([]))
      assert.equal(fs.existsSync(imagePath(waiting)), true)
      assert.equal(fs.readFileSync(paymentFile, 'utf8'), ledger)
    } finally { fs.renameSync = originalRename }
    const originalUnlink = fs.unlinkSync
    fs.unlinkSync = ((file) => {
      if (String(file) === imagePath(waiting)) throw new Error('Denied image delete')
      originalUnlink(file)
    }) as typeof fs.unlinkSync
    try { assert.throws(() => payments.cleanupProofs([])) } finally { fs.unlinkSync = originalUnlink }
    assert.equal(fs.existsSync(imagePath(waiting)), true)
    payments.cleanupProofs([])
    payments.cleanupProofs([])
    assert.equal(fs.existsSync(imagePath(waiting)), false)
    assert.deepEqual(JSON.parse(fs.readFileSync(paymentFile, 'utf8'))[eventName], {})
  } finally {
    await new Promise<void>(resolve => bot.close(() => resolve()))
    if (previousDir === undefined) delete process.env.BOT_DATA_DIR; else process.env.BOT_DATA_DIR = previousDir
    if (previousKey === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = previousKey
    if (previousBotUrl === undefined) delete process.env.BOT_ADMIN_URL; else process.env.BOT_ADMIN_URL = previousBotUrl
    fs.rmSync(dataDir, { recursive: true, force: true })
    fs.rmSync(modules, { recursive: true, force: true })
  }
})

test('admin removal route requires and forwards displayed registration identity and preserves bot conflicts', async () => {
  const modules = compileRoutes()
  const previousFetch = globalThis.fetch
  const previousKey = process.env.ADMIN_KEY
  const previousUrl = process.env.BOT_ADMIN_URL
  process.env.ADMIN_KEY = 'synthetic-test-key'
  process.env.BOT_ADMIN_URL = 'http://synthetic-bot'
  try {
    const route = await import(pathToFileURL(path.join(modules, 'api/registration/remove/route.js')).href)
    const calls: unknown[] = []
    globalThis.fetch = async (_url, options) => {
      calls.push(JSON.parse(options!.body as string))
      return Response.json({ error: 'registration_changed', removed: false }, { status: 409 })
    }
    const body = { event_name: 'Default event', user_id: uid }
    const url = '/api/registration/remove?key=synthetic-test-key'
    assert.equal((await route.POST(request(url, body))).status, 400)
    assert.equal((await route.POST(request(url, { ...body, registration_timestamp: 'bad' }))).status, 400)
    assert.deepEqual(calls, [])
    const response = await route.POST(request(url, { ...body, registration_timestamp: '2026-10-09T09:00:00+09:00' }))
    assert.equal(response.status, 409)
    assert.deepEqual(await response.json(), { error: 'registration_changed', removed: false })
    assert.deepEqual(calls, [{ ...body, registration_timestamp: '2026-10-09T00:00:00.000Z' }])
  } finally {
    globalThis.fetch = previousFetch
    if (previousKey === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = previousKey
    if (previousUrl === undefined) delete process.env.BOT_ADMIN_URL; else process.env.BOT_ADMIN_URL = previousUrl
    fs.rmSync(modules, { recursive: true, force: true })
  }
})
