import { getDrinkColors } from '../../lib/format'

export function DrinkCard({ name }: { name: string }) {
  const c = getDrinkColors(name)
  return (
    <div className={`${c.bg} rounded-xl border-2 ${c.border} px-4 py-3 relative overflow-hidden flex items-center gap-3 shadow-[3px_3px_0_#17120F]`}>
      <div className={`absolute left-0 top-0 bottom-0 w-2 ${c.strip}`} />
      <span className="font-black text-[#23110D] text-sm pl-2">{name}</span>
    </div>
  )
}
