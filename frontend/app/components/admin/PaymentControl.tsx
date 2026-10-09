'use client'
import { useEffect, useState } from 'react'
import { useT } from '../../lib/i18n'
import type { Attendee } from '../../lib/types'

export function PaymentControl({ attendee, adminKey, eventName, onPayment }: {
  attendee: Attendee; adminKey: string; eventName: string; onPayment: (userId: string, paid: boolean, timestamp: string) => Promise<boolean>
}) {
  const { t } = useT()
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const [previewImage, setPreviewImage] = useState<{ identity: string; url: string } | null>(null)
  const [previewFailure, setPreviewFailure] = useState<string | null>(null)
  const paid = attendee.payment?.paid ?? false
  const proof = attendee.payment?.proof
  const proofFilename = proof?.filename
  const proofUploadedAt = proof?.uploaded_at
  const registrationTimestamp = attendee.registration_timestamp
  const proofIdentity = `${eventName}:${attendee.user_id}:${registrationTimestamp}:${proofFilename}:${proofUploadedAt}`
  const previewUrl = preview && previewImage?.identity === proofIdentity ? previewImage.url : null
  const previewError = preview && previewFailure === proofIdentity
  useEffect(() => {
    if (!preview || !proofFilename || !proofUploadedAt || !registrationTimestamp) return
    const controller = new AbortController()
    let objectUrl: string | null = null
    const params = new URLSearchParams({ event: eventName, user_id: attendee.user_id,
      registration_timestamp: registrationTimestamp, proof_filename: proofFilename })
    fetch(`/api/payment-proof?${params}`, { headers: { Authorization: `Bearer ${adminKey}` }, signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('preview_failed')
        const blob = await response.blob()
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewImage({ identity: proofIdentity, url: objectUrl })
        setPreviewFailure(null)
      }).catch(() => { if (!controller.signal.aborted) setPreviewFailure(proofIdentity) })
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [preview, proofFilename, proofUploadedAt, proofIdentity, registrationTimestamp, eventName, attendee.user_id, adminKey])
  async function toggle() {
    if (!paid && !proof && !window.confirm(t.confirmPaidWithoutProof)) return
    if (!attendee.registration_timestamp) { setError(true); return }
    setBusy(true)
    setError(false)
    try { setError(!await onPayment(attendee.user_id, !paid, attendee.registration_timestamp)) } catch { setError(true) }
    finally { setBusy(false) }
  }
  if (!attendee.payment_enabled) return null
  if (attendee.payment_unavailable) return <p role="alert" className="border-t-2 border-[#17120F] bg-red-50 p-3 text-xs">{t.paymentUnavailable}</p>
  const paidButton = <button className="brand-action rounded-xl px-3 py-2" disabled={busy} onClick={toggle}>
    {paid ? t.markUnpaid : t.markPaid}
  </button>
  if (!paid && !proof) return <div className="border-t-2 border-[#17120F] bg-red-50 px-3 py-2 text-xs font-black">
    <details><summary className="cursor-pointer">{t.waitingForProof}</summary>
      <div className="pt-2">{paidButton}</div>
    </details>
    {error && <p role="alert" className="mt-2 text-red-700">{t.paymentSaveError}</p>}
  </div>
  return <div className={`border-t-2 border-[#17120F] text-xs ${paid ? 'bg-green-50' : 'bg-orange-50'}`}>
    <details open={!paid}>
      <summary className="cursor-pointer px-3 py-2 font-black">
        {paid ? t.paid : t.paymentPending}
        {attendee.payment_method && <span className="ml-3 font-normal">{attendee.payment_method}</span>}
      </summary>
      <div className="flex flex-wrap items-center gap-3 px-3 pb-3">
        {paidButton}
        {attendee.payment?.proof && <button className="brand-action-alt rounded-xl px-3 py-2"
          onClick={() => { setPreviewImage(null); setPreviewFailure(null); setPreview(v => !v) }}>{t.previewProof}</button>}
      </div>
      {previewUrl &&
        // eslint-disable-next-line @next/next/no-img-element
        <img src={previewUrl} alt={t.paymentProof} className="max-w-full max-h-96 rounded-xl p-3 pt-0" />}
    </details>
    {error && <p role="alert" className="px-3 pb-3 text-red-700">{t.paymentSaveError}</p>}
    {previewError && <p role="alert" className="px-3 pb-3 text-red-700">{t.paymentPreviewError}</p>}
  </div>
}
