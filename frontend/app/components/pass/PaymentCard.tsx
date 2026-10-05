'use client'
import { useRef, useState } from 'react'
import { useT } from '../../lib/i18n'
import type { PaymentRecord } from '../../lib/types'

export function PaymentCard({ token, method, instructions, instructionsJp, payment: initial, available }: {
  token: string; method: string | null; instructions: string | null; instructionsJp?: string | null; payment: PaymentRecord; available: boolean
}) {
  const { t, lang } = useT()
  const displayedInstructions = lang === 'ja' && instructionsJp?.trim() ? instructionsJp : instructions
  const [payment, setPayment] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(false)
  const [version, setVersion] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
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
      setFile(null)
    } catch { setError(t.paymentUploadError) } finally { setBusy(false) }
  }
  return <section className="brand-card rounded-2xl overflow-hidden">
    <details open={!payment.paid}>
    <summary className="bg-[#17120F] p-3 flex justify-between items-center cursor-pointer">
      <h2 className="text-[10px] font-black text-white tracking-[0.22em] uppercase">{t.payment}</h2>
      <span className={`text-[9px] font-black px-3 py-1 rounded border-2 uppercase tracking-widest border-white ${payment.paid ? 'bg-[#FFD51B] text-[#17120F]' : payment.proof ? 'bg-[#F59E0B] text-[#17120F]' : 'bg-[#E51F1F] text-white'}`}>
        {payment.paid ? t.paid : payment.proof ? t.paymentPending : t.unpaid}
      </span>
    </summary>
    <div className="p-5 space-y-3">
    {method && <p className="font-bold">{method}</p>}
    {displayedInstructions && <p className="whitespace-pre-wrap break-words text-sm">
      {displayedInstructions.split(/(https?:\/\/[^\s<>()]+)/g).map((part, index) => {
        if (!/^https?:\/\//.test(part)) return part
        const href = part.replace(/[.,;!?]+$/, '')
        return <span key={index}><a href={href} target="_blank" rel="noopener noreferrer"
          className="font-bold underline underline-offset-2">{href}</a>{part.slice(href.length)}</span>
      })}
    </p>}
    <p className="text-xs">{t.proofDoesNotMarkPaid}</p>
    {available ? <div className="space-y-2">
      <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,image/gif" disabled={busy}
        className="hidden" aria-label={t.chooseFile} onChange={e => {
          const selected = e.currentTarget.files?.[0]
          e.currentTarget.value = ''
          // Closing the picker without a file must not change the selection or start an upload.
          if (!selected) return
          setFile(selected)
          setError('')
        }} />
      <div className="flex flex-wrap gap-2">
        <button type="button" className="brand-action-alt min-h-[44px] rounded-xl px-4 py-2 font-black text-sm"
          disabled={busy} onClick={() => fileInput.current?.click()}>{t.chooseFile}</button>
        <button type="button" className="brand-action min-h-[44px] rounded-xl px-4 py-2 font-black text-sm disabled:opacity-50"
          disabled={busy || !file} onClick={() => upload(file ?? undefined)}>
          {busy ? t.loading : payment.proof ? t.replaceProof : t.uploadProof}
        </button>
      </div>
      <p className="break-words text-xs" role="status">{file?.name ?? t.noFileChosen}</p>
      <p className="text-xs">{t.paymentImageLimit}</p>
    </div> : <p className="text-xs">{t.proofExpired}</p>}
    {payment.proof && available && <button className="brand-action rounded-xl px-3 py-2"
      onClick={() => setPreview(v => !v)}>{t.previewProof}</button>}
    {preview && payment.proof && available &&
      // Authenticated private image; next/image's optimizer must not cache it.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={`/api/payment-proof?token=${encodeURIComponent(token)}&v=${version}`} alt={t.paymentProof}
        className="w-full rounded-xl" />}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    </div>
    </details>
  </section>
}
