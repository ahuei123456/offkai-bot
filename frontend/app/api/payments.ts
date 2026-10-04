import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import sharp from 'sharp'
import type { Event } from './db'

export interface ProofMetadata {
  filename: string
  uploaded_at: string
  expires_at: string
}
export interface PaymentRecord {
  paid: boolean
  paid_at?: string
  proof: ProofMetadata | null
}
type Payments = Record<string, Record<string, PaymentRecord>>
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
  return JSON.parse(fs.readFileSync(paymentsPath(), 'utf8'))
}
function atomicWrite(filename: string, contents: string | Buffer) {
  fs.mkdirSync(path.dirname(filename), { recursive: true })
  const temporary = `${filename}.${crypto.randomUUID()}.tmp`
  try {
    fs.writeFileSync(temporary, contents, { mode: 0o600 })
    fs.renameSync(temporary, filename)
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary)
  }
}
function writePayments(payments: Payments) {
  atomicWrite(paymentsPath(), JSON.stringify(payments, null, 2))
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
export function getPayment(eventName: string, userId: string): PaymentRecord {
  const record = storedPayment(readPayments(), eventName, userId)
  return { ...record, proof: record.proof && !proofExpired(record.proof) ? record.proof : null }
}
export function setPaid(eventName: string, userId: string, paid: boolean): PaymentRecord {
  // No awaits between read/update/atomic write in this single Node process.
  const payments = readPayments()
  const record = { ...storedPayment(payments, eventName, userId), paid }
  if (paid) record.paid_at = new Date().toISOString()
  else delete record.paid_at
  assignPayment(payments, eventName, userId, record)
  writePayments(payments)
  return getPayment(eventName, userId)
}
export async function normalizeProof(input: Buffer): Promise<Buffer> {
  if (!input.length || input.length > MAX_IMAGE_BYTES) throw new Error('Image must be at most 10 MiB')
  const image = sharp(input, { limitInputPixels: MAX_PIXELS, animated: false, failOn: 'error' })
  const metadata = await image.metadata()
  if (!['jpeg', 'png', 'webp', 'gif'].includes(metadata.format || '')) throw new Error('Unsupported image')
  return image.rotate().resize({ width: 1080, withoutEnlargement: true }).webp({ quality: 85 }).toBuffer()
}
export async function saveProof(eventName: string, userId: string, eventStart: string, input: Buffer) {
  const expiresAt = proofExpiry(eventStart)
  if (Date.parse(expiresAt) <= Date.now()) throw new Error('Payment proof retention has expired')
  const output = await normalizeProof(input)
  if (Date.parse(expiresAt) <= Date.now()) throw new Error('Payment proof retention has expired')
  // Image processing finishes before this short synchronous transaction.
  const payments = readPayments()
  const previous = storedPayment(payments, eventName, userId)
  const proof: ProofMetadata = {
    filename: `${crypto.randomUUID()}.webp`, uploaded_at: new Date().toISOString(), expires_at: expiresAt,
  }
  atomicWrite(proofPath(proof), output)
  const record = { ...previous, proof }
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
export function readProof(eventName: string, userId: string, eventStart: string): Buffer | null {
  if (Date.parse(proofExpiry(eventStart)) <= Date.now()) return null
  const proof = getPayment(eventName, userId).proof
  if (!proof || proofExpired(proof)) return null
  const filename = proofPath(proof)
  return fs.existsSync(filename) ? fs.readFileSync(filename) : null
}
export function cleanupProofs(events: Event[], now = Date.now()) {
  const payments = readPayments()
  let changed = false
  for (const [eventName, users] of Object.entries(payments)) {
    const event = events.find(e => e.event_name === eventName)
    for (const record of Object.values(users)) {
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
