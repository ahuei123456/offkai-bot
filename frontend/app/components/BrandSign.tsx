import { SmileyMark } from './SmileyMark'

// Shared izakaya wordmark. `variant` picks the pass (centered, with subtitle) or
// admin (left-aligned) layout; `compact` is the inline lockup used in headers.
export function BrandSign({
  compact = false,
  variant = 'admin',
  subtitle,
}: {
  compact?: boolean
  variant?: 'pass' | 'admin'
  subtitle?: string
}) {
  if (compact) {
    return (
      <div className="inline-flex items-center gap-1.5">
        <SmileyMark className="h-7 w-7 shrink-0 -rotate-6" />
        <span className="brand-wordmark text-2xl leading-none">Offkai Bot</span>
      </div>
    )
  }

  if (variant === 'pass') {
    return (
      <div className="inline-flex flex-col items-center px-2">
        <span className="brand-banner inline-block rounded-lg px-3 py-0.5 text-[11px] tracking-[0.34em]">大衆酒場</span>
        <div className="mt-2 flex items-center gap-1.5">
          <span className="brand-wordmark text-[2.4rem] leading-[0.95]">Offkai Bot</span>
          <SmileyMark className="h-8 w-8 shrink-0 -rotate-6 drop-shadow-[2px_2px_0_#17120F]" />
        </div>
        {subtitle && (
          <span className="mt-2 font-display text-[10px] uppercase tracking-[0.42em] text-white drop-shadow-[1.5px_1.5px_0_#17120F]">{subtitle}</span>
        )}
      </div>
    )
  }

  return (
    <div className="inline-flex flex-col items-start">
      <span className="brand-banner inline-block rounded-lg px-2.5 py-0.5 text-[10px] tracking-[0.3em]">大衆酒場</span>
      <div className="mt-1.5 flex items-end gap-1">
        <span className="brand-wordmark text-4xl leading-[0.9]">Offkai Bot</span>
        <SmileyMark className="mb-1 h-7 w-7 shrink-0 -rotate-6 drop-shadow-[2px_2px_0_#17120F]" />
      </div>
    </div>
  )
}
