// Pure sort logic for the two CEO Executive customer tables ("Profit by
// Customer" / "Worst Profit by Customer"). No React, no imports — kept pure so
// it can be exercised in isolation. The pinned Totals row is NOT a row here: it
// is rendered separately and can never be sorted into the list.

export type CustomerSortKey =
  | "customer"
  | "loads"
  | "revenue"
  | "profit"
  | "margin_pct"
  | "conc_pct"
  | "avg_p_per_l"

export type CustomerSortDir = "asc" | "desc"

export interface CustomerSort {
  readonly key: CustomerSortKey
  readonly dir: CustomerSortDir
}

export interface CustomerSortableRow {
  readonly customer: string
  readonly loads: number | null
  readonly revenue: number | null
  readonly profit: number | null
  readonly margin_pct: number | null
  readonly conc_pct: number | null
  readonly avg_p_per_l: number | null
}

export const CUSTOMER_COLUMNS: ReadonlyArray<{
  readonly key: CustomerSortKey
  readonly label: string
}> = [
  { key: "customer", label: "Customer" },
  { key: "loads", label: "Loads" },
  { key: "revenue", label: "Revenue" },
  { key: "profit", label: "Profit" },
  { key: "margin_pct", label: "Margin %" },
  { key: "conc_pct", label: "Conc %" },
  { key: "avg_p_per_l", label: "AVG P / L" },
]

/** First click on a column: text A→Z, numbers high→low. */
export function firstDirFor(key: CustomerSortKey): CustomerSortDir {
  return key === "customer" ? "asc" : "desc"
}

/** Header click: same column flips, a new column starts at its first dir. */
export function nextCustomerSort(current: CustomerSort, key: CustomerSortKey): CustomerSort {
  if (current.key === key) {
    return { key, dir: current.dir === "asc" ? "desc" : "asc" }
  }
  return { key, dir: firstDirFor(key) }
}

function isMissing(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))
}

function compareByKey(a: CustomerSortableRow, b: CustomerSortableRow, key: CustomerSortKey): number {
  if (key === "customer") {
    return a.customer.localeCompare(b.customer, "en-US", { sensitivity: "base", numeric: true })
  }
  return (a[key] as number) - (b[key] as number)
}

/**
 * Returns a NEW sorted array; the input is never mutated. Missing values sort
 * last in both directions; ties fall back to customer name A→Z so the order is
 * stable and deterministic.
 */
export function sortCustomerRows<T extends CustomerSortableRow>(
  rows: readonly T[],
  sort: CustomerSort,
): T[] {
  const sign = sort.dir === "asc" ? 1 : -1
  return [...rows].sort((a, b) => {
    const am = isMissing(a[sort.key])
    const bm = isMissing(b[sort.key])
    if (am && bm) return compareByKey(a, b, "customer")
    if (am) return 1
    if (bm) return -1
    const c = compareByKey(a, b, sort.key) * sign
    return c !== 0 ? c : compareByKey(a, b, "customer")
  })
}

export function sameCustomerSort(a: CustomerSort, b: CustomerSort): boolean {
  return a.key === b.key && a.dir === b.dir
}

/**
 * Subtitle for the table header. The default sort keeps the table's own
 * wording ("sorted by highest profit"); any other sort describes itself.
 */
export function describeCustomerSort(
  sort: CustomerSort,
  defaultSort: CustomerSort,
  defaultHint: string,
): string {
  if (sameCustomerSort(sort, defaultSort)) return defaultHint
  const label = CUSTOMER_COLUMNS.find((c) => c.key === sort.key)?.label ?? sort.key
  if (sort.key === "customer") {
    return `sorted by ${label} ${sort.dir === "asc" ? "A → Z" : "Z → A"}`
  }
  return `sorted by ${label} ${sort.dir === "desc" ? "high → low" : "low → high"}`
}

/** aria-sort value for a column header. */
export function ariaSortFor(
  sort: CustomerSort,
  key: CustomerSortKey,
): "ascending" | "descending" | "none" {
  if (sort.key !== key) return "none"
  return sort.dir === "asc" ? "ascending" : "descending"
}
