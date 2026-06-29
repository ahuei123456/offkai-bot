'use client'
import { useEffect, useRef } from 'react'
import { JST_HMS } from '../lib/format'

// Live JST clock with milliseconds — it visibly ticks, so staff can tell a real
// pass/check-in from a screenshot. Writes textContent through a ref in the rAF
// loop (no React state) so it never re-renders the tree while ticking.
export function LiveClock({ label = 'Live', className = '' }: { label?: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const d = new Date()
      const el = ref.current
      if (el) el.textContent = `${JST_HMS.format(d)}.${String(d.getMilliseconds()).padStart(3, '0')} JST`
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  return (
    <div className={`items-center justify-center gap-2 rounded-xl border-2 border-[#17120F] bg-[#17120F] px-3 py-1.5 ${className}`}>
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-[#3CCB5A]" aria-hidden="true" />
      <span className="text-[9px] font-black uppercase tracking-[0.2em] text-[#FFD51B]">{label}</span>
      <span ref={ref} className="font-mono text-sm font-black tabular-nums text-white" suppressHydrationWarning>--:--:--.--- JST</span>
    </div>
  )
}
