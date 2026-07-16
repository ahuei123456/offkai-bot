'use client'

import { useMemo, useState, type CSSProperties } from 'react'
import type { Attendee } from '../../lib/types'
import {
  buildNametagEntries,
  calculateSheetLayout,
  chunkNametagEntries,
  DEFAULT_NAMETAG_SHEET,
  normalizeSheetSettings,
  type NametagEntry,
  type NametagSheetSettings,
} from '../../lib/nametags'

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
      <span className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 rounded-lg border border-[#17120F]/35 bg-white px-2 focus-within:border-[#E51F1F] focus-within:ring-2 focus-within:ring-[#E51F1F]/20">
        <input
          type="number"
          step="0.1"
          value={value}
          onChange={event => onChange(Number(event.target.value))}
          className="w-full min-w-0 border-0 bg-transparent py-2 text-center text-sm font-black text-[#17120F] outline-none"
        />
        <span className="text-[9px] text-[#8B2D1F]/70">{suffix}</span>
      </span>
    </label>
  )
}

function clamp(min: number, value: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function textFitVars(entry: NametagEntry): CSSProperties {
  const words = entry.name.split(/\s+/).filter(Boolean)
  const longestWord = Math.max(...words.map(word => word.length), 0)
  const multiWordLoad = words.length > 1
    ? Math.max(longestWord * 1.25, (entry.name.length / (entry.kind === 'guest' ? 2.2 : 2)) * 1.25)
    : longestWord * 1.2
  const nameLoad = Math.max(multiWordLoad, entry.name.length * (entry.kind === 'guest' ? 0.48 : 0.55))
  const visualSubLine = entry.kind === 'guest' ? '' : entry.subLine
  const metaLoad = Math.max(entry.discordLine.length, visualSubLine.length)
  const guestPenalty = entry.kind === 'guest' ? 0.45 : 0
  const metaPenalty = visualSubLine ? clamp(0, metaLoad - 18, 34) * 0.03 : 0
  const nameMm = clamp(entry.kind === 'guest' ? 4.6 : 3.8, 10.8 - nameLoad * 0.17 - guestPenalty - metaPenalty, entry.kind === 'guest' ? 7.8 : 9.8)
  const discordMm = clamp(entry.kind === 'guest' ? 2.45 : 1.85, 4.25 - metaLoad * 0.04, visualSubLine ? 3.1 : entry.kind === 'guest' ? 3.35 : 3.9)
  const metaMm = clamp(1.4, 3 - visualSubLine.length * 0.035, 2.6)
  const nameRows = entry.kind === 'guest' ? 22 : nameLoad > 30 ? 22 : 25
  const metaRows = visualSubLine ? 10 : 8

  return {
    '--nametag-name-mm': `${nameMm.toFixed(2)}mm`,
    '--nametag-discord-mm': `${discordMm.toFixed(2)}mm`,
    '--nametag-meta-mm': `${metaMm.toFixed(2)}mm`,
    '--nametag-name-row-mm': `${nameRows}mm`,
    '--nametag-meta-row-mm': `${metaRows}mm`,
  } as CSSProperties
}

function EntrySticker({ entry, eventName }: { entry: NametagEntry; eventName: string }) {
  const nameClass = entry.name.length > 34
    ? 'nametag-card--name-xlong'
    : entry.name.length > 22
      ? 'nametag-card--name-long'
      : ''
  const showSubLine = entry.kind !== 'guest' && Boolean(entry.subLine)
  const metaClass = showSubLine ? 'nametag-card--with-meta' : ''
  const denseClass = entry.discordLine.length > 24 || entry.subLine.length > 24 ? 'nametag-card--dense' : ''
  const kindClass = entry.kind === 'guest' ? 'nametag-card--guest' : ''

  return (
    <article className={`nametag-card nametag-card--plain ${nameClass} ${metaClass} ${denseClass} ${kindClass}`} style={textFitVars(entry)}>
      <div className="nametag-card__header">
        <div>
          <p className="nametag-card__hello">ENTRY PASS</p>
          <p className="nametag-card__my-name">{eventName}</p>
        </div>
        <div className="nametag-card__number" aria-label={`Entry number ${entry.numberLabel}`}>
          <span>No.</span>
          <strong>{entry.numberLabel}</strong>
        </div>
      </div>
      <div className="nametag-card__body">
        <span className="nametag-card__stamp" aria-hidden="true">大衆酒場</span>
        <p className="nametag-card__name">{entry.name}</p>
        <div className="nametag-card__identity">
          <p className="nametag-card__discord">{entry.discordLine}</p>
          {showSubLine && <p className="nametag-card__meta-row">{entry.subLine}</p>}
        </div>
      </div>
      <div className="nametag-card__footer">
        <span>Offkai Bot</span>
        <strong>{entry.kind === 'guest' ? '+1 GUEST' : 'OFFKAI'}</strong>
      </div>
    </article>
  )
}

function BlankSticker({ eventName }: { eventName: string }) {
  return (
    <article className="nametag-card nametag-card--plain nametag-card--blank">
      <div className="nametag-card__header">
        <div>
          <p className="nametag-card__hello">ENTRY PASS</p>
          <p className="nametag-card__my-name">{eventName}</p>
        </div>
      </div>
      <div className="nametag-card__body">
        <span className="nametag-card__stamp" aria-hidden="true">大衆酒場</span>
        <div
          className="nametag-card__blank-lines"
          aria-hidden="true"
        >
          <span>&nbsp;</span>
          <span>&nbsp;</span>
        </div>
      </div>
      <div className="nametag-card__footer">
        <span>Offkai Bot</span>
        <strong>OFFKAI</strong>
      </div>
    </article>
  )
}

export function NametagSheetGenerator({ attendees, eventName }: { attendees: Attendee[]; eventName: string }) {
  const [settings, setSettings] = useState<NametagSheetSettings>(DEFAULT_NAMETAG_SHEET)
  const safeSettings = useMemo(() => normalizeSheetSettings(settings), [settings])
  const layout = useMemo(() => calculateSheetLayout(safeSettings), [safeSettings])
  const entries = useMemo(
    () => buildNametagEntries(attendees),
    [attendees]
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
          body { margin: 0 !important; background: white !important; }
          body * { visibility: hidden !important; }
          #nametag-print-root, #nametag-print-root * { visibility: visible !important; }
          body > div,
          main,
          [role="dialog"][aria-label="Nametag printer"],
          [role="dialog"][aria-label="Nametag printer"] > div,
          .brand-card,
          .brand-card > div:last-child,
          .brand-card > div:last-child > div:last-child {
            display: contents !important;
            visibility: visible !important;
          }
          [role="dialog"][aria-label="Nametag printer"] { position: static !important; inset: auto !important; overflow: visible !important; padding: 0 !important; background: white !important; backdrop-filter: none !important; }
          main > :not([role="dialog"]) { display: none !important; }
          #nametag-print-root { position: static !important; display: block !important; width: var(--paper-w) !important; zoom: 1 !important; }
          .nametag-print-controls { display: none !important; }
          .nametag-screen-preview { width: var(--paper-w) !important; zoom: 1 !important; }
          .nametag-sheet { height: calc(var(--paper-h) - 0.6mm) !important; min-height: 0 !important; overflow: hidden !important; box-shadow: none !important; margin: 0 !important; }
        }
      `}</style>

      <div className="nametag-print-controls border-b-4 border-[#17120F] bg-[#17120F] p-4 text-white md:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.24em] text-[#FFD51B]">Nametag printer</p>
            <h2 className="font-display text-2xl font-black uppercase tracking-tight md:text-3xl">Print-ready offkai stickers</h2>
            <p className="mt-1 text-xs font-bold text-white/70">Separate print tool. Not part of the day-of attendee list.</p>
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

      <div className="nametag-print-controls grid gap-4 border-b-2 border-[#17120F] bg-[#FFF8D8] p-4 md:p-5">
        <div className="grid gap-3 lg:grid-cols-[280px_1fr]">
          <div className="rounded-2xl border-2 border-[#17120F] bg-white p-4 shadow-[3px_3px_0_rgba(23,18,15,0.22)]">
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#8B2D1F]">Paper/template</p>
            <p className="mt-3 text-lg font-black uppercase leading-tight text-[#17120F]">Avery 5395 · Letter 2×4</p>
            <p className="mt-2 text-[11px] font-bold text-[#5B3428]">2⅓×3⅜in badges on US Letter stock. Waitlist hidden from print.</p>
          </div>

          <div className="rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] p-4 shadow-[3px_3px_0_rgba(23,18,15,0.22)]">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#8B2D1F]">Paper use</p>
                <p className="mt-1 text-sm font-black text-[#17120F]">
                  {entries.length}/{totalSlots} slots filled · {blankSlots} blank · {pages.length} page{pages.length === 1 ? '' : 's'} · gutters {safeSettings.gutterXMm}×{safeSettings.gutterYMm}mm
                </p>
              </div>
              <button
                type="button"
                onClick={() => window.print()}
                className="brand-action min-h-[48px] rounded-2xl px-5 py-3 text-xs font-black uppercase tracking-[0.18em]"
              >
                Print tags
              </button>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/85 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Paper</p>
                <Field label="Width" value={safeSettings.paperWidthMm} onChange={setNumber('paperWidthMm')} />
                <Field label="Height" value={safeSettings.paperHeightMm} onChange={setNumber('paperHeightMm')} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/85 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Sticker</p>
                <Field label="Width" value={safeSettings.stickerWidthMm} onChange={setNumber('stickerWidthMm')} />
                <Field label="Height" value={safeSettings.stickerHeightMm} onChange={setNumber('stickerHeightMm')} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/85 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Gutter</p>
                <Field label="X" value={safeSettings.gutterXMm} onChange={setNumber('gutterXMm')} />
                <Field label="Y" value={safeSettings.gutterYMm} onChange={setNumber('gutterYMm')} />
              </div>
              <div className="grid min-w-0 grid-cols-2 gap-2 rounded-xl bg-white/85 p-3">
                <p className="col-span-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#17120F]/70">Margins</p>
                <Field label="Top" value={safeSettings.marginTopMm} onChange={setNumber('marginTopMm')} />
                <Field label="Right" value={safeSettings.marginRightMm} onChange={setNumber('marginRightMm')} />
                <Field label="Bottom" value={safeSettings.marginBottomMm} onChange={setNumber('marginBottomMm')} />
                <Field label="Left" value={safeSettings.marginLeftMm} onChange={setNumber('marginLeftMm')} />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-[#F2DFA2] p-3 md:p-4">
        <div className="nametag-print-controls mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#8B2D1F]">Print section</p>
            <p className="text-xs font-bold text-[#5B3428]">Only the sheet below is sent to print/PDF.</p>
          </div>
        </div>

        <div className="mx-auto flex max-h-[75vh] w-fit max-w-full justify-center overflow-auto rounded-2xl border-2 border-[#17120F] bg-[#E8D395] p-4">
          <div id="nametag-print-root" className="nametag-sheet-stage nametag-screen-preview grid gap-6">
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
                    <EntrySticker key={entry.id} entry={entry} eventName={eventName} />
                  ))}
                  {Array.from({ length: pageIndex === pages.length - 1 ? blankSlots : 0 }, (_, index) => (
                    <BlankSticker key={`blank:${pageIndex}:${index}`} eventName={eventName} />
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
