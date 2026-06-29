export function SmileyMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <circle cx="20" cy="20" r="18" fill="#E51F1F" stroke="#17120F" strokeWidth="2.5" />
      <circle cx="13" cy="16.5" r="2.6" fill="#17120F" />
      <circle cx="27" cy="16.5" r="2.6" fill="#17120F" />
      <path d="M11 22 q9 11 18 0" fill="none" stroke="#17120F" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
