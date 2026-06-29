'use client'
import { BrandSign } from '../BrandSign'
import { formatEventLabel } from '../../lib/format'
import type { EventOption } from '../../lib/types'

export function StatHeader({
  eventName,
  events,
  selectedEvent,
  onChangeEvent,
  pendingCount,
  checkedInCount,
  attendingCount,
  waitlistCount,
  scanning,
  onToggleScan,
}: {
  eventName: string
  events: EventOption[]
  selectedEvent: string
  onChangeEvent: (next: string) => void
  pendingCount: number
  checkedInCount: number
  attendingCount: number
  waitlistCount: number
  scanning: boolean
  onToggleScan: () => void
}) {
  return (
    <div className="brand-sunburst text-white p-4 md:p-6 rounded-b-[1.5rem] md:rounded-b-[2rem] border-b-4 border-[#17120F] shadow-[0_6px_0_#17120F] md:shadow-[0_8px_0_#17120F]">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] font-black tracking-[0.22em] uppercase text-white/80 mb-1">Staff Check-In</p>
          <h1 className="font-display text-xl md:text-2xl uppercase tracking-tight leading-tight drop-shadow-[2px_2px_0_#17120F] break-words">{eventName}</h1>
          <span className="brand-stamp font-brush mt-2 inline-block -rotate-2 rounded-xl px-3 py-0.5 text-sm tracking-[0.12em]">受付中</span>
        </div>
        <div className="hidden sm:block shrink-0">
          <BrandSign compact />
        </div>
      </div>

      {/* Event selector (issue #77) */}
      {events.length > 0 && (
        <select
          value={selectedEvent}
          onChange={e => onChangeEvent(e.target.value)}
          aria-label="Select event"
          className="mt-3 w-full bg-white border-2 border-[#17120F] text-[#17120F] text-xs font-black rounded-xl px-3 py-2.5 outline-none appearance-none shadow-[3px_3px_0_#17120F]"
        >
          {events.map(ev => (
            <option key={ev.event_name} value={ev.event_name}>
              {formatEventLabel(ev)}
            </option>
          ))}
        </select>
      )}

      <div className="grid grid-cols-3 gap-2 mt-3 md:mt-4 text-[#17120F]">
        <div className="rounded-xl md:rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] p-2 md:p-3 shadow-[3px_3px_0_#17120F]">
          <p className="text-xl md:text-2xl font-black">{pendingCount}</p>
          <p className="text-[9px] uppercase opacity-70 tracking-widest font-black">Pending</p>
        </div>
        <div className="rounded-xl md:rounded-2xl border-2 border-[#17120F] bg-white p-2 md:p-3 shadow-[3px_3px_0_#17120F]">
          <p className="text-xl md:text-2xl font-black">{checkedInCount}</p>
          <p className="text-[9px] uppercase opacity-70 tracking-widest font-black">In</p>
        </div>
        <div className="rounded-xl md:rounded-2xl border-2 border-[#17120F] bg-[#17120F] p-2 md:p-3 text-white shadow-[3px_3px_0_#FFD51B]">
          <p className="text-xl md:text-2xl font-black">{attendingCount}</p>
          <p className="text-[9px] uppercase opacity-70 tracking-widest font-black">People</p>
        </div>
      </div>

      <div className="flex items-center gap-3 mt-3 md:mt-4">
        <p className="text-xs font-black text-white drop-shadow-[1px_1px_0_#17120F]">{checkedInCount} / {attendingCount} in · {waitlistCount} waitlist</p>
        <div className="flex-1" />
        <button
          onClick={onToggleScan}
          className={`min-h-[44px] px-4 py-2 rounded-xl font-black text-xs uppercase tracking-widest cursor-pointer ${scanning ? 'brand-action text-white' : 'brand-action-alt'}`}
        >
          {scanning ? 'Stop' : 'Scan'}
        </button>
      </div>
    </div>
  )
}
