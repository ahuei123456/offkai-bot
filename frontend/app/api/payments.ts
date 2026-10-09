import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import sharp from 'sharp'
import type { Event } from './db'
import { readResponses } from './db'
import { paymentRegistration } from './payment-access'

export interface ProofMetadata {
  filename: string
  uploaded_at: string
  expires_at: string
}
export interface PaymentRecord {
  registration_timestamp?: string
  paid: boolean
  paid_at?: string
  proof: ProofMetadata | null
}
type Payments = Record<string, Record<string, PaymentRecord>>
export class InvalidImageError extends Error {}
export class RegistrationChangedError extends Error {}
export class ProofExpiredError extends Error {}
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const MAX_PIXELS = 40_000_000

function dataDir() {
  return process.env.BOT_DATA_DIR || (fs.existsSync('/app/offkai-bot-data')
    ? '/app/offkai-bot-data' : path.join(process.cwd(), '..', 'data'))
}
function paymentsPath() { return path.join(dataDir(), 'payments.json') }
function proofsDir() { return path.join(dataDir(), 'payment-proofs') }
function readPayments(): Payments {
  if (!fs.existsSync(paymentsPath())) return {}
  // Fail closed on malformed state rather than overwriting payment records.
  const payments: Payments = JSON.parse(fs.readFileSync(paymentsPath(), 'utf8'))
  if (!payments || typeof payments !== 'object' || Array.isArray(payments)) throw new Error('Invalid payment storage')
  for (const users of Object.values(payments)) {
    if (!users || typeof users !== 'object' || Array.isArray(users)) throw new Error('Invalid payment storage')
    for (const record of Object.values(users)) {
      if (record && typeof record === 'object' && record.proof === undefined) record.proof = null
      if (!record || typeof record !== 'object' || typeof record.paid !== 'boolean' ||
          (record.proof !== null && (!record.proof || typeof record.proof.filename !== 'string' ||
            typeof record.proof.uploaded_at !== 'string' || typeof record.proof.expires_at !== 'string'))) {
        throw new Error('Invalid payment storage')
      }
    }
  }
  return payments
}
export function readPaymentSnapshot(): Payments | null {
  try { return readBoundPayments() } catch {
    console.error('Payment storage unavailable; writes remain disabled until repaired')
    return null
  }
}
export function registrationTimestamp(timestamp: string): string {
  if (!timestamp || !Number.isFinite(Date.parse(timestamp))) throw new Error('Missing registration timestamp')
  return new Date(timestamp).toISOString()
}
function atomicWrite(filename: string, contents: string | Buffer) {
  fs.mkdirSync(path.dirname(filename), { recursive: true })
  const temporary = `${filename}.${crypto.randomUUID()}.tmp`
  try {
    const fd = fs.openSync(temporary, 'w', 0o600)
    try { fs.writeFileSync(fd, contents); fs.fsyncSync(fd) } finally { fs.closeSync(fd) }
    fs.renameSync(temporary, filename)
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary)
  }
}
function writePayments(payments: Payments) {
  atomicWrite(paymentsPath(), JSON.stringify(payments, null, 2))
}
function bindLegacyPayments(payments: Payments, responses: ReturnType<typeof readResponses>) {
  let changed = false
  for (const [eventName, users] of Object.entries(payments)) {
    for (const [userId, record] of Object.entries(users)) {
      if (!record.paid || record.paid_at || record.registration_timestamp) continue
      const entries = responses[eventName]
      const attendee = [...(entries?.attendees || []), ...(entries?.waitlist || [])].find(a => a.user_id === userId)
      if (!attendee) continue
      record.registration_timestamp = registrationTimestamp(attendee.timestamp)
      if (record.proof && Date.parse(record.proof.uploaded_at) < Date.parse(attendee.timestamp)) record.proof = null
      changed = true
    }
  }
  return changed
}
function readBoundPayments(): Payments {
  const payments = readPayments()
  if (Object.values(payments).some(users => Object.values(users).some(r => r.paid && !r.paid_at && !r.registration_timestamp)) &&
      bindLegacyPayments(payments, readResponses(true))) writePayments(payments)
  return payments
}
function storedPayment(payments: Payments, eventName: string, userId: string): PaymentRecord {
  return Object.hasOwn(payments, eventName) && Object.hasOwn(payments[eventName], userId)
    ? payments[eventName][userId] : { paid: false, proof: null }
}
function assignPayment(payments: Payments, eventName: string, userId: string, record: PaymentRecord) {
  if (!Object.hasOwn(payments, eventName)) {
    Object.defineProperty(payments, eventName, { value: {}, enumerable: true, writable: true })
  }
  payments[eventName][userId] = record
}
function proofPath(proof: ProofMetadata): string {
  if (!/^[a-f0-9-]+\.webp$/.test(proof.filename)) throw new Error('Invalid proof filename')
  return path.join(proofsDir(), proof.filename)
}
function removeProof(proof: ProofMetadata) {
  const filename = proofPath(proof)
  if (fs.existsSync(filename)) fs.unlinkSync(filename)
}

// Calendar months in the event's authoring timezone (JST, no DST), with
// month-end clamping. First apply the existing frontend's three-hour end.
export function proofExpiry(eventStart: string): string {
  const end = new Date(new Date(eventStart).getTime() + (3 + 9) * 60 * 60 * 1000)
  if (!Number.isFinite(end.getTime())) throw new Error('Missing event date')
  const day = end.getUTCDate()
  end.setUTCDate(1)
  end.setUTCMonth(end.getUTCMonth() + 3)
  const lastDay = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0)).getUTCDate()
  end.setUTCDate(Math.min(day, lastDay))
  return new Date(end.getTime() - 9 * 60 * 60 * 1000).toISOString()
}
export function proofExpired(proof: ProofMetadata, now = Date.now()): boolean {
  return !Number.isFinite(Date.parse(proof.expires_at)) || Date.parse(proof.expires_at) <= now
}
export function paymentFromSnapshot(payments: Payments, eventName: string, userId: string, timestamp: string): PaymentRecord {
  const identity = registrationTimestamp(timestamp)
  const record = storedPayment(payments, eventName, userId)
  if (record.registration_timestamp) {
    if (record.registration_timestamp !== identity) return { paid: false, proof: null, registration_timestamp: identity }
    return { ...record, proof: record.proof && !proofExpired(record.proof) ? record.proof : null }
  }
  // Legacy records have no binding. Only evidence created after this signup can belong to it.
  const paid = record.paid && !!record.paid_at && Date.parse(record.paid_at) >= Date.parse(identity)
  const proof = record.proof && Date.parse(record.proof.uploaded_at) >= Date.parse(identity) && !proofExpired(record.proof)
    ? record.proof : null
  return { ...record, paid, proof, registration_timestamp: identity }
}
export function getPayment(eventName: string, userId: string, timestamp: string): PaymentRecord {
  return paymentFromSnapshot(readBoundPayments(), eventName, userId, timestamp)
}
export function setPaid(eventName: string, userId: string, paid: boolean, timestamp: string): PaymentRecord {
  // No awaits between read/update/atomic write in this single Node process.
  const payments = readBoundPayments()
  const previous = storedPayment(payments, eventName, userId)
  const record = { ...paymentFromSnapshot(payments, eventName, userId, timestamp), paid }
  if (paid) record.paid_at = new Date().toISOString()
  else delete record.paid_at
  assignPayment(payments, eventName, userId, record)
  writePayments(payments)
  if (previous.proof && previous.proof.filename !== record.proof?.filename) removeProof(previous.proof)
  return record
}
export async function normalizeProof(input: Buffer): Promise<Buffer> {
  try {
    if (!input.length || input.length > MAX_IMAGE_BYTES) throw new Error('Image must be at most 10 MiB')
    const image = sharp(input, { limitInputPixels: MAX_PIXELS, animated: false, failOn: 'error' })
    const metadata = await image.metadata()
    if (!['jpeg', 'png', 'webp', 'gif'].includes(metadata.format || '')) throw new Error('Unsupported image')
    return await image.rotate().resize({ width: 1080, withoutEnlargement: true }).webp({ quality: 85 }).toBuffer()
  } catch { throw new InvalidImageError('Invalid image') }
}
export async function saveProof(eventName: string, userId: string, eventStart: string, input: Buffer, timestamp: string) {
  const expiresAt = proofExpiry(eventStart)
  if (Date.parse(expiresAt) <= Date.now()) throw new ProofExpiredError('Payment proof retention has expired')
  const output = await normalizeProof(input)
  if (Date.parse(expiresAt) <= Date.now()) throw new ProofExpiredError('Payment proof retention has expired')
  const current = paymentRegistration(eventName, userId)
  if (!current || registrationTimestamp(current.attendee.timestamp) !== registrationTimestamp(timestamp)) {
    throw new RegistrationChangedError('Registration changed during upload')
  }
  // Image processing finishes before this short synchronous transaction.
  const payments = readBoundPayments()
  const previous = storedPayment(payments, eventName, userId)
  const proof: ProofMetadata = {
    filename: `${crypto.randomUUID()}.webp`, uploaded_at: new Date().toISOString(), expires_at: expiresAt,
  }
  atomicWrite(proofPath(proof), output)
  const record = { ...paymentFromSnapshot(payments, eventName, userId, timestamp), proof }
  try {
    assignPayment(payments, eventName, userId, record)
    writePayments(payments)
  } catch (error) {
    removeProof(proof)
    throw error
  }
  if (previous.proof) removeProof(previous.proof)
  return record
}
export function readProof(eventName: string, userId: string, eventStart: string, timestamp: string): Buffer | null {
  if (Date.parse(proofExpiry(eventStart)) <= Date.now()) return null
  const proof = getPayment(eventName, userId, timestamp).proof
  if (!proof || proofExpired(proof)) return null
  const filename = proofPath(proof)
  return fs.existsSync(filename) ? fs.readFileSync(filename) : null
}
export function cleanupProofs(events: Event[], now = Date.now()) {
  const payments = readPayments()
  // Missing/corrupt registrations must never be mistaken for an empty attendance list.
  const responses = readResponses(true)
  let changed = bindLegacyPayments(payments, responses)
  for (const [eventName, users] of Object.entries(payments)) {
    const event = events.find(e => e.event_name === eventName)
    for (const [userId, record] of Object.entries(users)) {
      const entries = responses[eventName]
      const live = [...(entries?.attendees || []), ...(entries?.waitlist || [])].find(a => a.user_id === userId)
      if (!live || (record.registration_timestamp && record.registration_timestamp !== registrationTimestamp(live.timestamp))) {
        delete users[userId]
        changed = true
        continue
      }
      if (record.proof && Date.parse(record.proof.uploaded_at) < Date.parse(live.timestamp)) {
        record.proof = null
        changed = true
      }
      if (!record.proof) continue
      // A changed event date cannot extend the expiry captured on upload.
      if (proofExpired(record.proof, now) || (event?.event_datetime &&
          Date.parse(proofExpiry(event.event_datetime)) <= now)) {
        removeProof(record.proof)
        record.proof = null
        changed = true
      }
    }
  }
  if (changed) writePayments(payments)
  // Recover orphan images left by a process crash during a replace transaction.
  if (fs.existsSync(proofsDir())) {
    const referenced = new Set(Object.values(payments).flatMap(users =>
      Object.values(users).flatMap(record => record.proof ? [record.proof.filename] : [])))
    for (const filename of fs.readdirSync(proofsDir())) {
      if (/^[a-f0-9-]+\.webp$/.test(filename) && !referenced.has(filename)) {
        fs.unlinkSync(path.join(proofsDir(), filename))
      }
    }
  }
}
