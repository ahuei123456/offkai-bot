'use client'
import { LiveClock } from '../LiveClock'
import { POPUP_MS, SCAN_RESULT_META } from '../../lib/scan'
import type { ScanResult } from '../../lib/types'

// Full-screen confirmation shown after a scan (or a setup/camera error) so staff
// instantly see who just checked in (and how big their party is).
export function ScanPopup({
  result,
  popupMsLeft,
  onDismiss,
}: {
  result: ScanResult
  popupMsLeft: number
  onDismiss: () => void
}) {
  const meta = SCAN_RESULT_META[result.kind]
  const party = 1 + (result.extraPeople ?? 0)
  const autoDismissing = result.fromScan && result.kind !== 'error'
  return (
    <div
      role={meta.ok ? 'status' : 'alert'}
      aria-live={meta.ok ? 'polite' : 'assertive'}
      onClick={onDismiss}
      className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-[#17120F]/70 backdrop-blur-sm cursor-pointer"
    >
      <div className={`brand-card w-full max-w-sm rounded-3xl border-4 border-[#17120F] p-8 text-center ${meta.ok ? 'bg-green-50' : 'bg-red-50'}`}>
        <span className={`mx-auto mb-4 inline-flex h-16 w-16 items-center justify-center rounded-full border-2 border-[#17120F] text-2xl font-black ${meta.ok ? 'bg-[#FFD51B] text-[#17120F]' : 'bg-[#E51F1F] text-white'}`}>
          {meta.ok ? '✓' : '✕'}
        </span>
        <p className={`font-display text-lg uppercase tracking-tight ${meta.ok ? 'text-green-800' : 'text-red-800'}`}>
          {meta.title}
        </p>
        {meta.ok && result.attendeeNumber != null && (
          <span className="mx-auto mt-3 inline-flex items-center gap-1.5 rounded-xl border-2 border-[#17120F] bg-[#FFD51B] px-3 py-1 text-[#17120F] shadow-[2px_2px_0_#17120F]">
            <span className="text-[9px] font-black uppercase tracking-widest">No.</span>
            <span className="font-display text-2xl font-black leading-none tabular-nums">{result.attendeeNumber}</span>
          </span>
        )}
        <p className="mt-2 font-black text-3xl leading-tight text-[#17120F] break-words">{result.name}</p>
        {meta.ok && party > 1 && (
          <p className="mt-2 text-sm font-black uppercase tracking-widest text-[#8B2D1F]">
            Party of {party}{result.extrasNumbers && result.extrasNumbers.length > 0 ? ` · guest no. ${result.extrasNumbers.map(n => `#${n}`).join(' · ')}` : ''}
          </p>
        )}
        {meta.ok && result.extrasNames && result.extrasNames.length > 0 && (
          <p className="mt-1 text-sm font-bold text-[#5B3428]">+{result.extrasNames.join(', ')}</p>
        )}
        {meta.ok && result.time && (
          <p className="mt-3 text-xs font-bold uppercase tracking-widest text-[#8B2D1F]/70">{result.time}</p>
        )}
        <div className="flex justify-center"><LiveClock className="mx-auto mt-3 inline-flex" /></div>
        {autoDismissing ? (
          <div className="mt-5">
            <div className="h-2 w-full overflow-hidden rounded-full border-2 border-[#17120F] bg-white">
              <div
                className={`h-full ${meta.ok ? 'bg-[#FFD51B]' : 'bg-[#E51F1F]'}`}
                style={{ width: `${(popupMsLeft / POPUP_MS[result.kind]) * 100}%` }}
              />
            </div>
            <p className="mt-2 font-mono text-[11px] font-black tabular-nums text-[#8B2D1F]">
              {Math.ceil(popupMsLeft)} ms · tap to scan next
            </p>
          </div>
        ) : (
          <p className="mt-5 text-[10px] font-black uppercase tracking-widest text-[#8B2D1F]/50">Tap to dismiss</p>
        )}
      </div>
    </div>
  )
}
