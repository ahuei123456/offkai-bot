'use client'
import { BrandSign } from '../BrandSign'

export function AdminLogin({
  keyInput,
  setKeyInput,
  loginError,
  onLogin,
}: {
  keyInput: string
  setKeyInput: (v: string) => void
  loginError: string
  onLogin: () => void
}) {
  return (
    <main className="brand-rays min-h-dvh flex items-center justify-center p-6">
      <div className="brand-card w-full max-w-sm rounded-3xl p-7">
        <BrandSign />
        <p className="mt-7 text-[10px] font-black uppercase tracking-[0.22em] text-[#8B2D1F]">Staff Access</p>
        <h1 className="mt-2 font-display text-2xl uppercase text-[#17120F] tracking-tight">Check-In Admin</h1>
        <label htmlFor="admin-key" className="block text-[10px] font-black uppercase tracking-widest text-[#8B2D1F] mt-6 mb-2">
          Admin key
        </label>
        <input
          id="admin-key"
          type="password"
          placeholder="Admin key"
          value={keyInput}
          onChange={e => setKeyInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !!keyInput.trim() && onLogin()}
          aria-invalid={!!loginError}
          aria-describedby={loginError ? 'admin-login-error' : undefined}
          className="w-full border-2 border-[#17120F] rounded-xl px-4 py-3 text-[#17120F] font-bold bg-white mb-2 outline-none focus:border-[#E51F1F]"
        />
        {loginError && (
          <p id="admin-login-error" role="alert" className="text-sm font-bold text-red-700 mb-3">{loginError}</p>
        )}
        <button
          onClick={onLogin}
          disabled={!keyInput.trim()}
          className="brand-action w-full font-black uppercase tracking-widest py-3 rounded-xl mt-2 disabled:opacity-50 disabled:shadow-none"
        >
          Enter
        </button>
      </div>
    </main>
  )
}
