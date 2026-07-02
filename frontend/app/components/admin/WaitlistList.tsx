'use client'
import type { Attendee } from '../../lib/types'

export function WaitlistList({ waitlist }: { waitlist: Attendee[] }) {
  if (waitlist.length === 0) return null
  return (
    <div className="mt-6">
      <p className="text-[9px] font-black uppercase tracking-widest text-[#8B2D1F] mb-2">Waitlist</p>
      <div className="space-y-2">
        {waitlist.map(a => (
          <div key={a.user_id} className="bg-[#FFD51B] rounded-2xl border-2 border-[#17120F] p-4 flex items-center gap-3 shadow-[4px_4px_0_rgba(23,18,15,0.25)]">
            <div className="w-8 h-8 rounded-full border-2 border-[#17120F] bg-white flex items-center justify-center font-black text-[#17120F] shrink-0">
              {(a.display_name || a.username)[0].toUpperCase()}
            </div>
            <p className="font-bold text-[#17120F] text-sm">{a.display_name || a.username}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
