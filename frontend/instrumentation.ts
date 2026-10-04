export async function register() {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return
  const { cleanupProofs } = await import('./app/api/payments')
  const { readEvents } = await import('./app/api/db')
  const state = globalThis as typeof globalThis & { paymentCleanup?: ReturnType<typeof setInterval> }
  if (state.paymentCleanup) return
  const sweep = () => {
    try { cleanupProofs(readEvents()) } catch (error) { console.error('Payment proof cleanup failed:', error) }
  }
  sweep()
  state.paymentCleanup = setInterval(sweep, 24 * 60 * 60 * 1000)
  state.paymentCleanup.unref()
}
