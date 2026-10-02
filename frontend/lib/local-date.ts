/**
 * Parse an API date as a LOCAL date.
 *
 * `new Date("2026-10-01")` is UTC midnight — Sep 30, 19:00 in CST — so its
 * label, `getDate()` and `getMonth()` all read one day (or month) early
 * (SPEC-CODE-RULES §116). A date-only "YYYY-MM-DD" is built from its parts at
 * local midnight instead; anything else (a full timestamp) keeps the native
 * parse.
 */
export function parseLocalDate(value: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!m) return new Date(value)
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}
