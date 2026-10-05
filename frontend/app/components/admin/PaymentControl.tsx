'use client'
import { useState } from 'react'
import { useT } from '../../lib/i18n'
import type { Attendee } from '../../lib/types'

export function PaymentControl({ attendee, adminKey, eventName, onPayment }: {
  attendee: Attendee; adminKey: string; eventName: string; onPayment: (userId: string, paid: boolean) => Promise<boolean>
}) {
  const { t } = useT()
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const paid = attendee.payment?.paid ?? false
  const proof = attendee.payment?.proof
  async function toggle() {
    setBusy(true)
    setError(false)
    try { setError(!await onPayment(attendee.user_id, !paid)) } catch { setError(true) }
    finally { setBusy(false) }
  }
  const url = `/api/payment-proof?key=${encodeURIComponent(adminKey)}&event=${encodeURIComponent(eventName)}&user_id=${encodeURIComponent(attendee.user_id)}&v=${encodeURIComponent(attendee.payment?.proof?.uploaded_at ?? '')}`
  if (!paid && !proof) return <div className="border-t-2 border-[#17120F] bg-red-50 px-3 py-2 text-xs font-black">
    {t.waitingForProof}
  </div>
  return <div className={`border-t-2 border-[#17120F] text-xs ${paid ? 'bg-green-50' : 'bg-orange-50'}`}>
    <details open={!paid}>
      <summary className="cursor-pointer px-3 py-2 font-black">
        {paid ? t.paid : t.paymentPending}
        {attendee.payment_method && <span className="ml-3 font-normal">{attendee.payment_method}</span>}
      </summary>
      <div className="flex flex-wrap items-center gap-3 px-3 pb-3">
        {(paid || proof) && <button className="brand-action rounded-xl px-3 py-2" disabled={busy} onClick={toggle}>
          {paid ? t.markUnpaid : t.markPaid}
        </button>}
        {attendee.payment?.proof && <button className="brand-action-alt rounded-xl px-3 py-2"
          onClick={() => setPreview(v => !v)}>{t.previewProof}</button>}
      </div>
      {preview && attendee.payment?.proof &&
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={t.paymentProof} className="max-w-full max-h-96 rounded-xl p-3 pt-0" />}
    </details>
    {error && <p role="alert" className="px-3 pb-3 text-red-700">{t.paymentSaveError}</p>}
  </div>
}
