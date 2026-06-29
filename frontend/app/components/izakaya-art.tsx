// Decorative izakaya SVG art for the attendee pass header (lantern garland +
// karaage boat). Purely presentational, all aria-hidden.

function Lantern({ className = '', delay = '0s', variant = 'red', glyph = '祭' }: { className?: string; delay?: string; variant?: 'red' | 'gold'; glyph?: string }) {
  const body = variant === 'gold' ? '#FFC400' : '#E51F1F'
  const glyphFill = variant === 'gold' ? '#9A1414' : '#FFF8D8'
  return (
    <svg
      viewBox="0 0 44 74"
      className={className}
      style={{ transformOrigin: 'top center', animation: 'lanternSway 3.4s ease-in-out infinite', animationDelay: delay }}
      aria-hidden="true"
    >
      <line x1="22" y1="0" x2="22" y2="8" stroke="#17120F" strokeWidth="2" />
      <rect x="11" y="7" width="22" height="7" rx="2.5" fill="#3A2A1A" stroke="#17120F" strokeWidth="2" />
      <ellipse cx="22" cy="35" rx="18" ry="21" fill={body} stroke="#17120F" strokeWidth="2.5" />
      <ellipse cx="15" cy="29" rx="4" ry="8" fill="#FFFFFF" opacity="0.22" />
      <g stroke="#17120F" strokeOpacity="0.32" strokeWidth="1.5" fill="none">
        <path d="M5.5 27 Q22 24 38.5 27" />
        <path d="M4 35 Q22 32 40 35" />
        <path d="M5.5 43 Q22 46 38.5 43" />
      </g>
      <text x="22" y="41" textAnchor="middle" fontSize="18" fontWeight="700" fill={glyphFill} style={{ fontFamily: "'Hiragino Kaku Gothic ProN','Yu Gothic',sans-serif" }}>{glyph}</text>
      <rect x="14" y="54" width="16" height="6" rx="2" fill="#3A2A1A" stroke="#17120F" strokeWidth="2" />
      <g stroke="#FFC400" strokeWidth="2" strokeLinecap="round">
        <line x1="18" y1="60" x2="17" y2="71" /><line x1="22" y1="60" x2="22" y2="72" /><line x1="26" y1="60" x2="27" y2="71" />
      </g>
    </svg>
  )
}

export function LanternGarland() {
  const lanterns = [
    { g: '大', v: 'red' }, { g: '衆', v: 'gold' }, { g: '酒', v: 'red' }, { g: '場', v: 'gold' },
    { g: '乾', v: 'red' }, { g: '杯', v: 'gold' }, { g: '祭', v: 'red' },
  ] as const
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 px-1.5" aria-hidden="true">
      <div className="absolute left-2 right-2 top-1.5 h-0.5 rounded-full bg-[#17120F]/70" />
      <div className="relative flex items-start justify-between">
        {lanterns.map((l, i) => (
          <Lantern key={i} variant={l.v} glyph={l.g} delay={`${i * 0.22}s`} className={i % 2 ? 'h-9' : 'h-[2.9rem]'} />
        ))}
      </div>
    </div>
  )
}

function KaraagePiece({ x, y, s = 1, rot = 0 }: { x: number; y: number; s?: number; rot?: number }) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`}>
      <path
        d="M0 -13 C5 -13 7 -10 9 -9 C13 -9 14 -5 13 -2 C15 2 13 6 10 7 C9 11 5 13 1 11 C-3 13 -8 11 -8 7 C-12 6 -13 1 -11 -3 C-13 -7 -9 -11 -5 -10 C-4 -12 -2 -13 0 -13 Z"
        fill="#C36A18" stroke="#17120F" strokeWidth="2.2" strokeLinejoin="round"
      />
      <path d="M-5 -6 C-1 -8 4 -7 5 -3 C6 0 3 3 -1 2 C-5 2 -7 -3 -5 -6 Z" fill="#E89A40" />
      <circle cx="4" cy="5" r="1.2" fill="#3A2410" />
      <circle cx="-3" cy="6" r="1" fill="#3A2410" />
      <circle cx="6" cy="-2" r="0.9" fill="#3A2410" />
    </g>
  )
}

export function KaraageBoat({ className = '' }: { className?: string }) {
  const pieces = [
    { x: 46, y: 98, s: 1, rot: -8 }, { x: 72, y: 104, s: 1.1, rot: 12 }, { x: 102, y: 106, s: 1.18, rot: -4 },
    { x: 134, y: 104, s: 1.1, rot: 14 }, { x: 162, y: 98, s: 1, rot: -10 },
    { x: 60, y: 84, s: 1, rot: 18 }, { x: 90, y: 86, s: 1.05, rot: -14 }, { x: 120, y: 86, s: 1.05, rot: 8 }, { x: 150, y: 84, s: 1, rot: -18 },
    { x: 78, y: 68, s: 0.95, rot: -6 }, { x: 108, y: 68, s: 1, rot: 12 }, { x: 136, y: 68, s: 0.95, rot: -12 },
    { x: 94, y: 56, s: 0.92, rot: 8 }, { x: 122, y: 56, s: 0.92, rot: -8 }, { x: 108, y: 46, s: 0.85, rot: 2 },
  ]
  const negi = [
    { x: 72, y: 40 }, { x: 80, y: 24 }, { x: 86, y: 14 }, { x: 92, y: 8 }, { x: 98, y: 4, green: true }, { x: 103, y: 12 },
    { x: 108, y: 2 }, { x: 113, y: 8, green: true }, { x: 118, y: 0 }, { x: 123, y: 8 }, { x: 128, y: 2 },
    { x: 133, y: 10, green: true }, { x: 138, y: 4 }, { x: 144, y: 14 }, { x: 150, y: 22, green: true }, { x: 158, y: 36 },
    { x: 100, y: 16 }, { x: 114, y: 14 }, { x: 128, y: 18 }, { x: 66, y: 30 },
  ]
  return (
    <svg viewBox="0 0 240 168" className={className} aria-hidden="true">
      <g stroke="#FFFFFF" strokeWidth="3" strokeLinecap="round" fill="none" opacity="0.6">
        <path d="M84 14 q-7 -9 0 -17 q5 -6 0 -12" /><path d="M120 8 q-7 -9 0 -17 q5 -6 0 -12" /><path d="M156 16 q-7 -9 0 -17 q5 -6 0 -12" />
      </g>
      <g strokeLinecap="round" strokeWidth="3.6">
        {negi.map((n, i) => (
          <line key={i} x1="115" y1="56" x2={n.x} y2={n.y} stroke={n.green ? '#7FB84A' : '#FCFCF7'} />
        ))}
      </g>
      <path d="M88 54 Q104 40 120 44 Q138 39 152 54 Q138 62 120 60 Q100 63 88 54 Z" fill="#FCFCF7" stroke="#17120F" strokeWidth="1.6" strokeLinejoin="round" />
      {pieces.map((p, i) => <KaraagePiece key={i} {...p} />)}
      <g stroke="#17120F" strokeWidth="2" strokeLinejoin="round">
        <path d="M40 102 a15 15 0 0 1 15 15 l-15 0 z" fill="#FFE34D" />
        <path d="M40 102 a15 15 0 0 1 15 15" fill="none" stroke="#E8C200" strokeWidth="2" />
        <path d="M196 102 a15 15 0 0 0 -15 15 l15 0 z" fill="#FFE34D" />
      </g>
      <path d="M6 108 Q120 99 234 108 L210 130 Q120 152 30 130 Z" fill="#A9743C" stroke="#17120F" strokeWidth="2.6" strokeLinejoin="round" />
      <path d="M6 108 Q120 99 234 108 L228 113 Q120 105 12 113 Z" fill="#C28E50" stroke="#17120F" strokeWidth="1.5" />
      <path d="M26 118 Q120 130 214 118" fill="none" stroke="#6B4521" strokeWidth="2.4" strokeLinecap="round" />
      <g stroke="#6B4521" strokeWidth="1.4" strokeOpacity="0.55" strokeLinecap="round">
        <line x1="60" y1="124" x2="60" y2="134" /><line x1="100" y1="128" x2="100" y2="139" />
        <line x1="140" y1="128" x2="140" y2="139" /><line x1="180" y1="124" x2="180" y2="134" />
      </g>
    </svg>
  )
}
