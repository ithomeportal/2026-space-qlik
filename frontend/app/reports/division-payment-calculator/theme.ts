/**
 * Design tokens for the Division Payment Calculator.
 *
 * The RGB values below are specified verbatim in Bruno's PDF (Dashboard
 * Request 1 and Request 4) — they are a requirement, not a preference:
 *
 *   container      RGB(42, 55, 74)     · the navy payment hero
 *   profit         RGB(255, 255, 255)  · white, in the formula strip
 *   deductions     RGB(255, 100, 103)  · red
 *   corporate gain RGB(184, 146, 58)   · gold
 *   tariff callout RGB(255, 251, 235)  · pale amber panel background
 *
 * Everything else follows the prototype's palette so the port is recognisable.
 * ⚠ Light mode only — the portal blocks dark mode, and the prototype's dark
 * tokens were unreachable there too (`ThemeProvider defaultTheme="light"` with
 * `switchable` unset).
 */

export const DPC = {
  /** RGB(42, 55, 74) — the payment container. */
  container: "#2A374A",
  containerTo: "#334155",
  navy: "#1e293b",
  navyDeep: "#0f172a",
  /** RGB(184, 146, 58) — corporate gain / accent. */
  gold: "#B8923A",
  goldHover: "#a07e30",
  /** RGB(255, 100, 103) — deductions. */
  deduction: "#FF6467",
  /** RGB(255, 255, 255) — profit. */
  profit: "#FFFFFF",
  /** RGB(255, 251, 235) — the tariff explainer panel. */
  tariffPanel: "#FFFBEB",
  offWhite: "#faf9f7",
  border: "#e2e8f0",
  muted: "#64748b",
  secondary: "#475569",
  danger: "#dc2626",
  positive: "#16a34a",
} as const

/** Category colours, mirrored from the backend's ``CATEGORY_COLORS``. The
 *  server ships the colour with each category so these stay in step; this map
 *  is only the fallback for a category the server does not know. */
export const CATEGORY_FALLBACK = "#64748b"

/** Financial figures use tabular numerals so columns line up. The prototype
 *  loaded JetBrains Mono from Google Fonts; the portal already ships a mono
 *  stack, and adding a webfont for one report is not worth the CSP surface. */
export const MONO = "font-mono tabular-nums"
