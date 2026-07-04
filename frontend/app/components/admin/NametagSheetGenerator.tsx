'use client'

import { useMemo, useState } from 'react'
import type { Attendee } from '../../lib/types'
import {
  buildNametagEntries,
  calculateSheetLayout,
  chunkNametagEntries,
  DEFAULT_NAMETAG_SHEET,
  normalizeSheetSettings,
  type NametagEntry,
  type NametagSheetSettings,
  type StickerTheme,
} from '../../lib/nametags'

const PRESETS = [
  { label: 'A4 stonks · 3×5 full sheet', hint: 'default: no blank slots for the mock run', values: DEFAULT_NAMETAG_SHEET },
  {
    label: 'Letter · 3×8 Avery-ish',
    hint: 'US paper stock',
    values: {
      ...DEFAULT_NAMETAG_SHEET,
      paperWidthMm: 215.9,
      paperHeightMm: 279.4,
      marginTopMm: 12.7,
      marginRightMm: 4.8,
      marginBottomMm: 12.7,
      marginLeftMm: 4.8,
      stickerWidthMm: 66,
      stickerHeightMm: 33.9,
      gutterXMm: 2.5,
      gutterYMm: 0,
    },
  },
  {
    label: 'Compact badge · 91×55mm',
    hint: 'large readable cards',
    values: {
      ...DEFAULT_NAMETAG_SHEET,
      paperWidthMm: 210,
      paperHeightMm: 297,
      marginTopMm: 8,
      marginRightMm: 8,
      marginBottomMm: 8,
      marginLeftMm: 8,
      stickerWidthMm: 91,
      stickerHeightMm: 55,
      gutterXMm: 6,
      gutterYMm: 6,
    },
  },
]

function Field({
  label,
  value,
  onChange,
  suffix = 'mm',
}: {
  label: string
  value: number
  onChange: (next: number) => void
  suffix?: string
}) {
  return (
    <label className="grid gap-1 text-[10px] font-black uppercase tracking-[0.12em] text-[#5B3428]">
      <span>{label}</span>
      <span className="flex items-center gap-1 rounded-lg border border-[#17120F]/35 bg-white px-2 focus-within:border-[#E51F1F] focus-within:ring-2 focus-within:ring-[#E51F1F]/20">
        <input
          type="number"
          step="0.1"
          value={value}
          onChange={event => onChange(Number(event.target.value))}
          className="w-0 min-w-0 flex-1 border-0 bg-transparent py-2 text-sm font-black text-[#17120F] outline-none"
        />
        <span className="text-[9px] text-[#8B2D1F]/70">{suffix}</span>
      </span>
    </label>
  )
}

function EntrySticker({ entry, eventName, theme }: { entry: NametagEntry; eventName: string; theme: StickerTheme }) {
  const themeClass = {
    chibachan: 'nametag-card--chibachan',
    'classic-red': 'nametag-card--classic',
    ink: 'nametag-card--ink',
  }[theme]

  return (
    <article className={`nametag-card ${themeClass}`}>
      <div className="nametag-card__header">
        <div>
          <p className="nametag-card__hello">HELLO</p>
          <p className="nametag-card__my-name">OFFKAI NAME TAG</p>
        </div>
        <div className="nametag-card__number" aria-label={`Entry number ${entry.numberLabel}`}>
          <span>No.</span>
          <strong>{entry.numberLabel}</strong>
        </div>
      </div>
      <div className="nametag-card__body">
        <p className="nametag-card__name">{entry.name}</p>
        <p className="nametag-card__discord">{entry.discordLine}</p>
        <div className="nametag-card__meta-row">
          <span>{entry.subLine}</span>
          <span>{entry.kind === 'guest' ? 'GUEST' : entry.status.toUpperCase()}</span>
        </div>
      </div>
      <div className="nametag-card__footer">
        <span>{eventName}</span>
        <strong>千葉ちゃん</strong>
      </div>
    </article>
  )
}

export function NametagSheetGenerator({ attendees, eventName }: { attendees: Attendee[]; eventName: string }) {
  const [settings, setSettings] = useState<NametagSheetSettings>(DEFAULT_NAMETAG_SHEET)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const safeSettings = useMemo(() => normalizeSheetSettings(settings), [settings])
  const layout = useMemo(() => calculateSheetLayout(safeSettings), [safeSettings])
  const entries = useMemo(
    () => buildNametagEntries(attendees, { includeWaitlist: safeSettings.includeWaitlist }),
    [attendees, safeSettings.includeWaitlist]
  )
  const pages = useMemo(() => chunkNametagEntries(entries, layout.perPage), [entries, layout.perPage])
  const totalSlots = pages.length * layout.perPage
  const blankSlots = Math.max(0, totalSlots - entries.length)

  const update = (patch: Partial<NametagSheetSettings>) => setSettings(prev => normalizeSheetSettings({ ...prev, ...patch }))
  const setNumber = (key: keyof NametagSheetSettings) => (next: number) => update({ [key]: next } as Partial<NametagSheetSettings>)

  return (
    <section className="brand-card overflow-hidden rounded-3xl bg-[#FFF8D8]">
      <style>{`
        .nametag-sheet-stage {
          --paper-w: ${safeSettings.paperWidthMm}mm;
          --paper-h: ${safeSettings.paperHeightMm}mm;
          --margin-top: ${safeSettings.marginTopMm}mm;
          --margin-right: ${safeSettings.marginRightMm}mm;
          --margin-bottom: ${safeSettings.marginBottomMm}mm;
          --margin-left: ${safeSettings.marginLeftMm}mm;
          --sticker-w: ${safeSettings.stickerWidthMm}mm;
          --sticker-h: ${safeSettings.stickerHeightMm}mm;
          --gutter-x: ${safeSettings.gutterXMm}mm;
          --gutter-y: ${safeSettings.gutterYMm}mm;
        }
        @page { size: ${safeSettings.paperWidthMm}mm ${safeSettings.paperHeightMm}mm; margin: 0; }
        @media print {
          body { background: white !important; }
          body * { visibility: hidden !important; }
          #nametag-print-root, #nametag-print-root * { visibility: visible !important; }
          #nametag-print-root { position: absolute !important; inset: 0 auto auto 0 !important; width: var(--paper-w) !important; }
          .nametag-print-controls { display: none !important; }
          .nametag-sheet { box-shadow: none !important; margin: 0 !important; break-after: page; page-break-after: always; }
          .nametag-sheet:last-child { break-after: auto; page-break-after: auto; }
        }
      `}</style>

      <div className="nametag-print-controls border-b-4 border-[#17120F] bg-[#17120F] p-4 text-white md:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.24em] text-[#FFD51B]">Nametag printer</p>
            <h2 className="font-display text-2xl font-black uppercase tracking-tight md:text-3xl">Print-ready offkai stickers</h2>
            <p className="mt-1 text-xs font-bold text-white/70">Setup stays here. Only the paper section below prints.</p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-[#17120F] sm:min-w-[360px]">
            <div className="rounded-xl bg-[#FFD51B] px-3 py-2">
              <p className="text-[10px] font-black uppercase tracking-[0.12em] opacity-70">Stickers</p>
              <p className="text-xl font-black">{entries.length}</p>
            </div>
            <div className="rounded-xl bg-white px-3 py-2">
              <p className="text-[10px] font-black uppercase tracking-[0.12em] opacity-70">Sheet</p>
              <p className="text-xl font-black">{layout.columns}×{layout.rows}</p>
            </div>
            <div className="rounded-xl bg-white px-3 py-2">
              <p className="text-[10px] font-black uppercase tracking-[0.12em] opacity-70">Pages</p>
              <p className="text-xl font-black">{pages.length}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="nametag-print-controls grid gap-4 border-b-2 border-[#17120F] bg-[#FFF8D8] p-4 lg:grid-cols-[320px_1fr] md:p-5">
        <div className="rounded-2xl border-2 border-[#17120F] bg-white p-4 shadow-[3px_3px_0_rgba(23,18,15,0.22)]">
          <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#8B2D1F]">Quick setup</p>
          <div className="mt-3 grid gap-3">
            <label className="grid gap-1 text-[10px] font-black uppercase tracking-[0.12em] text-[#5B3428]">
              Preset
              <select
                aria-label="Nametag sheet preset"
                onChange={event => {
                  const preset = PRESETS[Number(event.target.value)]
                  if (preset) setSettings(preset.values)
                }}
                className="rounded-xl border-2 border-[#17120F] bg-white px-3 py-2.5 text-sm font-black text-[#17120F]"
              >
                {PRESETS.map((preset, index) => <option key={preset.label} value={index}>{preset.label}</option>)}
              </select>
            </label>

            <label className="grid gap-1 text-[10px] font-black uppercase tracking-[0.12em] text-[#5B3428]">
              Visual style
              <select
                value={safeSettings.theme}
                onChange={event => update({ theme: event.target.value as StickerTheme })}
                className="rounded-xl border-2 border-[#17120F] bg-white px-3 py-2.5 text-sm font-black text-[#17120F]"
              >
                <option value="chibachan">Chibachan clean</option>
                <option value="classic-red">Classic hello red</option>
                <option value="ink">Black ink staff mode</option>
              </select>
            </label>

            <label className="flex items-center gap-3 rounded-xl border-2 border-[#17120F] bg-[#FFF8D8] px-3 py-2.5 text-sm font-black text-[#17120F]">
              <input
                type="checkbox"
                checked={safeSettings.includeWaitlist}
                onChange={event => update({ includeWaitlist: event.target.checked })}
                className="h-5 w-5 accent-[#E51F1F]"
              />
              Include waitlist
            </label>
          </div>
        </div>

        <div className="rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] p-4 shadow-[3px_3px_0_rgba(23,18,15,0.22)]">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#8B2D1F]">Paper use</p>
              <p className="mt-1 text-sm font-black text-[#17120F]">
                {entries.length}/{totalSlots} slots filled · {blankSlots} blank · {pages.length} page{pages.length === 1 ? '' : 's'}
              </p>
              <p className="mt-1 text-xs font-bold text-[#5B3428]">Default is fitted now. Use custom paper only when the actual sticker stock demands it.</p>
            </div>
            <button
              type="button"
              onClick={() => window.print()}
              className="brand-action min-h-[48px] rounded-2xl px-5 py-3 text-xs font-black uppercase tracking-[0.18em]"
            >
              Print this section
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowAdvanced(prev => !prev)}
            className="mt-4 text-xs font-black uppercase tracking-[0.16em] text-[#17120F] underline decoration-[#E51F1F] decoration-2 underline-offset-4"
          >
            {showAdvanced ? 'Hide custom paper settings' : 'Custom paper settings'}
          </button>

          {showAdvanced && (
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/80 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Paper</p>
                <Field label="Width" value={safeSettings.paperWidthMm} onChange={setNumber('paperWidthMm')} />
                <Field label="Height" value={safeSettings.paperHeightMm} onChange={setNumber('paperHeightMm')} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/80 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Sticker</p>
                <Field label="Width" value={safeSettings.stickerWidthMm} onChange={setNumber('stickerWidthMm')} />
                <Field label="Height" value={safeSettings.stickerHeightMm} onChange={setNumber('stickerHeightMm')} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/80 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Gutter</p>
                <Field label="X" value={safeSettings.gutterXMm} onChange={setNumber('gutterXMm')} />
                <Field label="Y" value={safeSettings.gutterYMm} onChange={setNumber('gutterYMm')} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/80 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Margins</p>
                <Field label="Top" value={safeSettings.marginTopMm} onChange={setNumber('marginTopMm')} />
                <Field label="Right" value={safeSettings.marginRightMm} onChange={setNumber('marginRightMm')} />
                <Field label="Bottom" value={safeSettings.marginBottomMm} onChange={setNumber('marginBottomMm')} />
                <Field label="Left" value={safeSettings.marginLeftMm} onChange={setNumber('marginLeftMm')} />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-[#F2DFA2] p-4 md:p-6">
        <div className="nametag-print-controls mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#8B2D1F]">Print section</p>
            <p className="text-xs font-bold text-[#5B3428]">This framed paper is the only thing sent to print/PDF.</p>
          </div>
        </div>

        <div className="overflow-auto rounded-2xl border-2 border-[#17120F] bg-[#E8D395] p-3">
          <div id="nametag-print-root" className="nametag-sheet-stage grid gap-6">
            {pages.map((pageEntries, pageIndex) => (
              <div
                key={pageIndex}
                className="nametag-sheet bg-white"
                style={{
                  width: `${safeSettings.paperWidthMm}mm`,
                  minHeight: `${safeSettings.paperHeightMm}mm`,
                  paddingTop: `${safeSettings.marginTopMm}mm`,
                  paddingRight: `${safeSettings.marginRightMm}mm`,
                  paddingBottom: `${safeSettings.marginBottomMm}mm`,
                  paddingLeft: `${safeSettings.marginLeftMm}mm`,
                }}
              >
                <div
                  className="nametag-grid"
                  style={{
                    gridTemplateColumns: `repeat(${layout.columns}, ${safeSettings.stickerWidthMm}mm)`,
                    gridAutoRows: `${safeSettings.stickerHeightMm}mm`,
                    columnGap: `${safeSettings.gutterXMm}mm`,
                    rowGap: `${safeSettings.gutterYMm}mm`,
                  }}
                >
                  {pageEntries.map(entry => (
                    <EntrySticker key={entry.id} entry={entry} eventName={eventName} theme={safeSettings.theme} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
