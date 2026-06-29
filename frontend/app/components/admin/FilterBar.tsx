'use client'
import type { AdminFilter } from '../../lib/types'

// Sticky filter tabs + search. Pins to the top so they stay reachable while
// scrolling a long attendee list (the header above scrolls away).
export function FilterBar({
  filter,
  onChangeFilter,
  search,
  onSearch,
}: {
  filter: AdminFilter
  onChangeFilter: (f: AdminFilter) => void
  search: string
  onSearch: (v: string) => void
}) {
  return (
    <div className="sticky top-0 z-20 bg-[#FFF1C2] border-b-2 border-[#17120F]/15 px-4 py-3 space-y-2.5 shadow-[0_6px_10px_-6px_rgba(23,18,15,0.4)] lg:px-6">
      <div className="flex gap-2">
        {(['all', 'pending', 'checked'] as const).map(f => (
          <button
            key={f}
            onClick={() => onChangeFilter(f)}
            aria-pressed={filter === f}
            className={`min-h-[44px] px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer border-2 border-[#17120F] ${filter === f ? 'bg-[#17120F] text-white shadow-[3px_3px_0_#FFD51B]' : 'bg-[#FFF8D8] text-[#17120F] shadow-[3px_3px_0_rgba(23,18,15,0.25)]'}`}
          >
            {f}
          </button>
        ))}
      </div>
      <input
        id="attendee-search"
        type="search"
        aria-label="Search attendee"
        placeholder="Search name, drink, guest, #id, @handle..."
        value={search}
        onChange={e => onSearch(e.target.value)}
        className="w-full border-2 border-[#17120F] rounded-xl px-4 py-3 text-sm font-bold bg-white text-[#17120F] outline-none focus:border-[#E51F1F] shadow-[3px_3px_0_rgba(23,18,15,0.25)]"
      />
    </div>
  )
}
