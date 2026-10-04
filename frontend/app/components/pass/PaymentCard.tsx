'use client'
import { useState } from 'react'
import { useT } from '../../lib/i18n'
import type { PaymentRecord } from '../../lib/types'

export function PaymentCard({ token, method, instructions, payment: initial, available }: {
  token: string; method: string | null; instructions: string | null; payment: PaymentRecord; available: boolean
}) {
  const { t } = useT()
  const [payment, setPayment] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(false)
  const [version, setVersion] = useState(0)
  async function upload(file?: File) {
    if (!file) return
    if (file.size > 10 * 1024 * 1024) { setError(t.paymentImageLimit); return }
    setBusy(true)
    setError('')
    const form = new FormData()
    form.set('token', token)
    form.set('image', file)
    try {
      const response = await fetch('/api/payment-proof', { method: 'POST', body: form })
      const data = await response.json()
      if (!response.ok) throw new Error(t.paymentUploadError)
      setPayment(data.payment)
      setVersion(v => v + 1)
      setPreview(true)
    } catch { setError(t.paymentUploadError) } finally { setBusy(false) }
  }
  return <section className="brand-card rounded-2xl p-5 space-y-3">
    <h2 className="font-black">{t.payment}</h2>
    {method && <p className="font-bold">{method}</p>}
    {instructions && <p className="whitespace-pre-wrap break-words text-sm">{instructions}</p>}
    <p className="font-bold">{payment.paid ? t.paid : t.unpaid}</p>
    <p className="text-xs">{t.proofDoesNotMarkPaid}</p>
    {available ? <label className="block font-bold text-sm">
      {busy ? t.loading : payment.proof ? t.replaceProof : t.uploadProof}
      <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" disabled={busy}
        className="mt-2 block w-full text-xs" onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }} />
      <span className="text-xs">{t.paymentImageLimit}</span>
    </label> : <p className="text-xs">{t.proofExpired}</p>}
    {payment.proof && available && <button className="brand-action rounded-xl px-3 py-2"
      onClick={() => setPreview(v => !v)}>{t.previewProof}</button>}
    {preview && payment.proof && available &&
      // Authenticated private image; next/image's optimizer must not cache it.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={`/api/payment-proof?token=${encodeURIComponent(token)}&v=${version}`} alt={t.paymentProof}
        className="w-full rounded-xl" />}
    {error && <p role="alert" className="text-red-700">{error}</p>}
  </section>
}
