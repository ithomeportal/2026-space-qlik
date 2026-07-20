// Shared timestamp/countdown formatters for the status='A' board views
// ("Pending to Cover", Bruno PDF 2026-07-15 R16; "Cover", Bruno PDF 2026-07-20 R1).
// Extracted from ByOrder.tsx so both tables can live in their own files.

// Format a CST wall-clock ISO ("YYYY-MM-DDTHH:MM:SS") as "MMM d, HH:MM".
// The backend already sentinel-guards 1900-01-01 to null, so a null here means
// the load genuinely has no scheduled pickup window.
export function fmtSchedTs(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso.replace(" ", "T"))
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  })
}

// Bruno (PDF 2026-07-15) R16: "Time to Cover" = hours remaining until the late
// pickup deadline. >48h green (plenty of runway), 24–48h amber, <24h (incl.
// overdue) red.
export function timeToCoverColor(hours: number): string {
  if (hours >= 48) return "text-[#16A34A]"
  if (hours >= 24) return "text-[#B45309]"
  return "font-medium text-[#DC2626]"
}

export function fmtTimeToCover(hours: number | null): string {
  if (hours == null) return "—"
  const abs = Math.abs(hours)
  const label = abs < 48 ? `${Math.round(abs)}h` : `${Math.round(abs / 24)}d`
  return hours < 0 ? `−${label} overdue` : label
}
