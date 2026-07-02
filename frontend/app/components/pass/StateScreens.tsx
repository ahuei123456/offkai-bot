'use client'
import { useT, LangToggle } from '../../lib/i18n'
import { BrandSign } from '../BrandSign'

// Full-screen loading splash (shared by the Suspense fallback and the
// in-flight fetch state).
export function LoadingScreen({ label }: { label?: string }) {
  return (
    <div className="brand-rays min-h-dvh flex items-center justify-center">
      <div className={`brand-seal px-5 py-3 text-sm font-black uppercase tracking-widest text-white ${label ? 'animate-pulse' : ''}`}>
        {label ?? 'Loading...'}
      </div>
    </div>
  )
}

function CenterCard({ children }: { children: React.ReactNode }) {
  return (
    <main className="brand-rays min-h-dvh flex flex-col items-center justify-center p-6 text-[#23110D]">
      <div className="mb-4 w-full max-w-sm flex justify-end">
        <LangToggle />
      </div>
      <div className="brand-card w-full max-w-sm rounded-3xl p-7 text-center">
        {children}
      </div>
    </main>
  )
}

export function NoToken() {
  const { t } = useT()
  return (
    <CenterCard>
      <BrandSign compact />
      <h1 className="mt-7 font-display text-2xl uppercase tracking-tight">{t.checkDms}</h1>
      <p className="mt-3 text-sm font-bold leading-relaxed text-[#5B3428]">{t.checkDmsBody}</p>
    </CenterCard>
  )
}

export function InvalidToken({ reason }: { reason: 'invalid' | 'not_found' | 'unavailable' }) {
  const { t } = useT()
  const title = reason === 'not_found' ? t.rsvpNotFound : reason === 'unavailable' ? t.rsvpUnavailable : t.linkInvalid
  const badge = reason === 'not_found' ? '404' : reason === 'unavailable' ? '503' : 'NG'
  const message =
    reason === 'not_found' ? t.notFoundBody
      : reason === 'unavailable' ? t.unavailableBody
        : t.invalidBody
  return (
    <CenterCard>
      <BrandSign compact />
      <p className="mx-auto mt-7 inline-flex h-12 min-w-12 items-center justify-center rounded-full border-2 border-[#17120F] bg-[#E51F1F] px-4 text-sm font-black uppercase tracking-widest text-white">
        {badge}
      </p>
      <h1 className="mt-4 font-display text-2xl uppercase tracking-tight">{title}</h1>
      <p className="mt-3 text-sm font-bold leading-relaxed text-[#5B3428]">{message}</p>
      {reason === 'unavailable' && (
        <button
          onClick={() => window.location.reload()}
          className="brand-action mt-5 min-h-[44px] rounded-xl px-6 font-black uppercase tracking-widest text-sm"
        >
          {t.retry}
        </button>
      )}
    </CenterCard>
  )
}
