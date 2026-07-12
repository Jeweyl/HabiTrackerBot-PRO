/** Date helpers for dashboard range queries (local calendar days). */

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

export function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Inclusive window ending today: last `days` calendar days. */
export function rangeLastDays(days: number, today: Date = new Date()): {
  from: string
  to: string
} {
  const safeDays = Math.max(1, Math.min(90, Math.floor(days) || 7))
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const start = new Date(end)
  start.setDate(start.getDate() - (safeDays - 1))
  return { from: toIsoDate(start), to: toIsoDate(end) }
}

export function formatShortDate(iso: string): string {
  // YYYY-MM-DD → MM-DD (stable, no locale crash on empty)
  if (!iso || iso.length < 10) {
    return iso || "—"
  }
  return iso.slice(5)
}
