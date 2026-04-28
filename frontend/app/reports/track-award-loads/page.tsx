"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { AlertCircle, ArrowDown, ArrowLeft, ArrowUp, ArrowUpDown, Award, Loader2, Minus, X } from "lucide-react"
import {
  useTalByAwardLane,
  useTalByCustomer,
  useTalByCustomerAward,
  useTalByDivision,
  useTalFilters,
  useTalKpis,
  type TalAwardLaneSort,
  type TalFilters,
  type TalByAwardLaneRow,
  type TalByCustomerAwardRow,
  type TalByCustomerRow,
  type TalByDivisionRow,
} from "@/lib/track-award-loads-api"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"
import { ErrorBanner } from "./ErrorBanner"
import { daysExpClass, fmtDate, fmtInt, fmtMoney, fmtPct } from "./format"

type TabKey = "division" | "customer" | "customer-award" | "award-lane"

const TABS: { key: TabKey; label: string }[] = [
  { key: "division",       label: "By Division" },
  { key: "customer",       label: "By Customer" },
  { key: "customer-award", label: "By Customer & Award" },
  { key: "award-lane",     label: "By Award & Lane" },
]

// ---------------------------------------------------------------------------
// Page wrapper
// ---------------------------------------------------------------------------

export default function TrackAwardLoadsPage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["track-award-loads"]]}>
      <Suspense
        fallback={
          <div className="flex min-h-[60vh] items-center justify-center text-xs text-[#6B7280]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading…
          </div>
        }
      >
        <Content />
      </Suspense>
    </RoleGuard>
  )
}

// ---------------------------------------------------------------------------
// Main content
// ---------------------------------------------------------------------------

function Content() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const filters: TalFilters = useMemo(
    () => ({
      statuses: parseList(searchParams.get("status")),
      divisions: parseList(searchParams.get("division")),
      customerIds: parseList(searchParams.get("customer_id")),
      awardNames: parseList(searchParams.get("award_name")),
    }),
    [searchParams],
  )

  const tab = (searchParams.get("tab") as TabKey) || "division"
  const laneSort =
    (searchParams.get("lane_sort") as TalAwardLaneSort) || "days_asc"

  const updateUrl = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined || v === "") next.delete(k)
        else next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

  const setTab = (k: TabKey) => updateUrl({ tab: k === "division" ? null : k })
  const setLaneSort = (s: TalAwardLaneSort) =>
    updateUrl({ lane_sort: s === "days_asc" ? null : s })

  const setFilter = (key: keyof TalFilters, values: string[]) => {
    const param = {
      statuses: "status",
      divisions: "division",
      customerIds: "customer_id",
      awardNames: "award_name",
    }[key]
    updateUrl({ [param]: values.length ? values.join(",") : null })
  }

  const filterRes = useTalFilters()
  const filterOptions = filterRes.data?.data
  const kpisQ = useTalKpis(filters)
  const divQ = useTalByDivision(filters)
  const custQ = useTalByCustomer(filters)
  const caQ = useTalByCustomerAward(filters)
  const lanesQ = useTalByAwardLane(filters, laneSort)

  const kpis = kpisQ.data?.data
  const asOf = filterOptions?.as_of
  const anyFilter =
    filters.statuses.length +
      filters.divisions.length +
      filters.customerIds.length +
      filters.awardNames.length >
    0

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Top bar */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link
          href="/"
          className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <Award className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Track Award Loads
          </h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            primary awards
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          {asOf && <span>Snapshot: {fmtDate(asOf)}</span>}
          {filterRes.isFetching && (
            <Loader2 className="h-3 w-3 animate-spin text-[#6B7280]" />
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto grid w-full max-w-[1920px] grid-cols-1 gap-3 px-6 py-3 md:grid-cols-2 lg:grid-cols-4">
          <FilterPill
            label="Status"
            options={filterOptions?.statuses ?? []}
            selected={filters.statuses}
            onChange={(v) => setFilter("statuses", v)}
          />
          <FilterPill
            label="Division"
            options={filterOptions?.divisions ?? []}
            selected={filters.divisions}
            onChange={(v) => setFilter("divisions", v)}
          />
          <FilterPill
            label="Customer ID"
            options={filterOptions?.customer_ids ?? []}
            selected={filters.customerIds}
            onChange={(v) => setFilter("customerIds", v)}
            searchable
          />
          <FilterPill
            label="Award Name"
            options={filterOptions?.award_names ?? []}
            selected={filters.awardNames}
            onChange={(v) => setFilter("awardNames", v)}
            searchable
          />
        </div>
        {anyFilter && (
          <div className="border-t border-[#F3F4F6] bg-[#F9FAFB] px-6 py-1.5 text-[11px] text-[#6B7280]">
            <button
              onClick={() => {
                setFilter("statuses", [])
                setFilter("divisions", [])
                setFilter("customerIds", [])
                setFilter("awardNames", [])
              }}
              className="font-semibold text-[#1B3A5C] hover:underline"
            >
              Clear all filters
            </button>
          </div>
        )}
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-4">
        <ExpiryBanner
          rows={lanesQ.data?.data?.rows ?? []}
          loading={lanesQ.isLoading}
          onJumpToDeepest={() => {
            setTab("award-lane")
            setLaneSort("days_asc")
            // small scroll nudge so the user lands on the table
            setTimeout(() => {
              window.scrollTo({ top: window.innerHeight * 0.4, behavior: "smooth" })
            }, 50)
          }}
        />
        <ErrorBanner
          errors={[
            kpisQ.error,
            divQ.error,
            custQ.error,
            caQ.error,
            lanesQ.error,
            filterRes.error,
          ]}
          label="Track Award Loads"
        />

        {/* KPI containers */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <KpiContainer
            title="Lanes"
            accent="#0891B2"
            bgAccent="#ECFEFF"
            borderAccent="#A5F3FC"
            kpis={[
              {
                label: "Unique Lanes Awarded",
                value: fmtInt(kpis?.lanes.unique_lanes_awarded),
              },
              {
                label: "Unique Actual Lanes",
                value: fmtInt(kpis?.lanes.unique_actual_lanes),
              },
              {
                label: "Lane Variance",
                value: fmtSignedInt(kpis?.lanes.lane_variance),
              },
            ]}
            ratio={kpis?.lanes.ratio}
            loading={kpisQ.isLoading}
          />
          <KpiContainer
            title="Volume"
            accent="#DC2626"
            bgAccent="#FEF2F2"
            borderAccent="#FECACA"
            kpis={[
              {
                label: "Awarded Volume",
                value: fmtInt(kpis?.volume.awarded_volume),
              },
              {
                label: "Total Actual Volume",
                value: fmtInt(kpis?.volume.total_actual_volume),
              },
              {
                label: "Load Variance",
                value: fmtSignedInt(kpis?.volume.load_variance),
              },
            ]}
            ratio={kpis?.volume.ratio}
            loading={kpisQ.isLoading}
          />
          <KpiContainer
            title="Profit"
            accent="#CA8A04"
            bgAccent="#FEFCE8"
            borderAccent="#FEF08A"
            kpis={[
              {
                label: "Projected Profit",
                value: fmtMoney(kpis?.profit.projected_profit),
              },
              {
                label: "Actual Profit",
                value: fmtMoney(kpis?.profit.actual_profit),
              },
              {
                label: "Profit Variance",
                value: fmtSignedMoney(kpis?.profit.profit_variance),
              },
            ]}
            ratio={kpis?.profit.ratio}
            loading={kpisQ.isLoading}
          />
          <KpiContainer
            title="Carrier Cost"
            accent="#059669"
            bgAccent="#ECFDF5"
            borderAccent="#A7F3D0"
            kpis={[
              {
                label: "Projected Carrier Cost",
                value: fmtMoney(kpis?.carrier_cost.projected_carrier_cost),
              },
              {
                label: "Actual Carrier Cost",
                value: fmtMoney(kpis?.carrier_cost.actual_carrier_cost),
              },
              {
                label: "Carrier Cost Variance",
                value: fmtSignedMoney(kpis?.carrier_cost.variance),
              },
            ]}
            ratio={kpis?.carrier_cost.ratio}
            loading={kpisQ.isLoading}
          />
        </div>

        {/* Tab strip */}
        <div className="flex flex-wrap items-center gap-1 border-b border-[#E5E7EB] bg-white px-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-3 py-2 text-xs font-semibold transition-colors ${
                tab === t.key
                  ? "border-[#1B3A5C] text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab body */}
        {tab === "division" && (
          <DivisionTable
            rows={divQ.data?.data?.rows ?? []}
            loading={divQ.isLoading}
          />
        )}
        {tab === "customer" && (
          <CustomerTable
            rows={custQ.data?.data?.rows ?? []}
            loading={custQ.isLoading}
          />
        )}
        {tab === "customer-award" && (
          <CustomerAwardTable
            rows={caQ.data?.data?.rows ?? []}
            loading={caQ.isLoading}
          />
        )}
        {tab === "award-lane" && (
          <AwardLaneTable
            rows={lanesQ.data?.data?.rows ?? []}
            loading={lanesQ.isLoading}
            sort={laneSort}
            setSort={setLaneSort}
          />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter pill (multi-select dropdown, pure HTML — no Base UI / cmdk)
// ---------------------------------------------------------------------------

function FilterPill({
  label,
  options,
  selected,
  onChange,
  searchable,
}: {
  label: string
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
  searchable?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const filtered = useMemo(() => {
    if (!searchable || !query) return options
    const q = query.toLowerCase()
    return options.filter((o) => o.toLowerCase().includes(q))
  }, [options, query, searchable])
  const summary =
    selected.length === 0
      ? "All"
      : selected.length === 1
        ? selected[0]
        : `${selected.length} selected`

  return (
    <div className="relative">
      <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </label>
      <button
        onClick={() => setOpen((v) => !v)}
        className="mt-1 flex w-full items-center justify-between rounded-md border border-[#E5E7EB] bg-white px-3 py-1.5 text-xs text-[#374151] hover:bg-[#F9FAFB]"
      >
        <span className="max-w-[14rem] truncate">{summary}</span>
        <span className="text-[#6B7280]">▾</span>
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-20"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 right-0 z-30 mt-1 max-h-64 overflow-auto rounded-md border border-[#E5E7EB] bg-white p-1 text-xs shadow-lg">
            {searchable && (
              <input
                type="text"
                placeholder="Search…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="mb-1 w-full rounded border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              />
            )}
            <div className="flex items-center justify-between border-b border-[#F3F4F6] px-2 py-1">
              <span className="text-[10px] text-[#6B7280]">
                {selected.length} / {options.length}
              </span>
              <button
                onClick={() => onChange([])}
                className="rounded px-1.5 py-0.5 text-[10px] text-[#1B3A5C] hover:bg-[#F3F4F6]"
              >
                Clear
              </button>
            </div>
            {filtered.length === 0 && (
              <div className="px-2 py-2 text-[10px] text-[#6B7280]">No matches</div>
            )}
            {filtered.map((opt) => {
              const on = selected.includes(opt)
              return (
                <label
                  key={opt}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-[#F3F4F6]"
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      onChange(
                        on ? selected.filter((s) => s !== opt) : [...selected, opt],
                      )
                    }
                    className="h-3 w-3"
                  />
                  <span className="flex-1 truncate">{opt}</span>
                </label>
              )
            })}
          </div>
        </>
      )}
      {selected.length > 0 && (
        <button
          onClick={() => onChange([])}
          className="absolute right-2 top-7 rounded-full bg-[#F3F4F6] p-0.5 text-[#6B7280] hover:bg-[#E5E7EB]"
          aria-label={`Clear ${label}`}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// KPI container (mirrors the PDF: 3 numbers + a % progress bar)
// ---------------------------------------------------------------------------

function KpiContainer({
  title,
  accent,
  bgAccent,
  borderAccent,
  kpis,
  ratio,
  loading,
}: {
  title: string
  accent: string
  bgAccent: string
  borderAccent: string
  kpis: { label: string; value: string }[]
  ratio: number | null | undefined
  loading?: boolean
}) {
  const pct = ratio == null ? null : ratio * 100
  // Cap visual bar at 200% — the PDF shows up to 11964% so we just label it.
  const barWidth = pct == null ? 0 : Math.min(200, Math.max(0, pct))
  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: bgAccent, borderColor: borderAccent }}
    >
      <div className="mb-2 text-xs font-semibold" style={{ color: accent }}>
        {title}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {kpis.map((k) => (
          <div key={k.label}>
            <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              {k.label}
            </div>
            <div
              className="mt-1 text-base font-semibold tabular-nums"
              style={{ color: accent }}
            >
              {loading ? "…" : k.value}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3">
        <div className="flex items-center justify-between text-[10px] text-[#6B7280]">
          <span>0%</span>
          <span>100%</span>
        </div>
        <div
          className="h-2 w-full overflow-hidden rounded-full"
          style={{ background: "rgba(0,0,0,0.06)" }}
        >
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${(barWidth / 200) * 100}%`,
              background: accent,
              opacity: 0.9,
            }}
          />
        </div>
        <div className="mt-1 text-right text-[11px] font-semibold tabular-nums" style={{ color: accent }}>
          {pct == null ? "—" : `${pct.toFixed(2)}%`}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

const AGG_HEADERS: { label: string; key: keyof DummyRowAgg; numeric?: boolean; money?: boolean }[] = [
  { label: "Unique Lanes Awarded", key: "unique_lanes_awarded", numeric: true },
  { label: "Awarded Volume",       key: "awarded_volume", numeric: true },
  { label: "Total Actual Volume",  key: "total_actual_volume", numeric: true },
  { label: "Load Variance",        key: "load_variance", numeric: true },
  { label: "Projected Profit",     key: "projected_profit", numeric: true, money: true },
  { label: "Actual Profit",        key: "actual_profit", numeric: true, money: true },
  { label: "Profit Variance",      key: "profit_variance", numeric: true, money: true },
  { label: "Projected Carrier Cost", key: "projected_carrier_cost", numeric: true, money: true },
  { label: "Actual Carrier Cost",  key: "actual_carrier_cost", numeric: true, money: true },
  { label: "Carrier Cost Variance", key: "carrier_cost_variance", numeric: true, money: true },
]

interface DummyRowAgg {
  unique_lanes_awarded: number
  awarded_volume: number
  total_actual_volume: number
  load_variance: number
  projected_profit: number
  actual_profit: number
  profit_variance: number
  projected_carrier_cost: number
  actual_carrier_cost: number
  carrier_cost_variance: number
}

function AggCells({ row }: { row: DummyRowAgg }) {
  return (
    <>
      {AGG_HEADERS.map((h) => {
        const v = row[h.key] as number
        const cls =
          h.key.includes("variance") && v < 0
            ? "text-[#991B1B]"
            : h.key.includes("variance") && v > 0
              ? "text-[#065F46]"
              : ""
        return (
          <td key={h.key as string} className={`px-3 py-1.5 text-right tabular-nums ${cls}`}>
            {h.money ? fmtMoney(v) : fmtInt(v)}
          </td>
        )
      })}
    </>
  )
}

function totalRow<T extends DummyRowAgg>(rows: T[]): DummyRowAgg | null {
  if (rows.length === 0) return null
  const t: DummyRowAgg = {
    unique_lanes_awarded: 0,
    awarded_volume: 0,
    total_actual_volume: 0,
    load_variance: 0,
    projected_profit: 0,
    actual_profit: 0,
    profit_variance: 0,
    projected_carrier_cost: 0,
    actual_carrier_cost: 0,
    carrier_cost_variance: 0,
  }
  for (const r of rows) {
    t.unique_lanes_awarded += r.unique_lanes_awarded
    t.awarded_volume += r.awarded_volume
    t.total_actual_volume += r.total_actual_volume
    t.load_variance += r.load_variance
    t.projected_profit += r.projected_profit
    t.actual_profit += r.actual_profit
    t.profit_variance += r.profit_variance
    t.projected_carrier_cost += r.projected_carrier_cost
    t.actual_carrier_cost += r.actual_carrier_cost
    t.carrier_cost_variance += r.carrier_cost_variance
  }
  return t
}

function TableShell({
  loading,
  empty,
  children,
}: {
  loading: boolean
  empty: boolean
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          {children}
          {loading && (
            <tbody>
              <tr>
                <td colSpan={20} className="px-3 py-8 text-center text-[#6B7280]">
                  <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />
                  Loading…
                </td>
              </tr>
            </tbody>
          )}
          {!loading && empty && (
            <tbody>
              <tr>
                <td colSpan={20} className="px-3 py-8 text-center text-[#6B7280]">
                  No rows match the current filters.
                </td>
              </tr>
            </tbody>
          )}
        </table>
      </div>
    </section>
  )
}

function DivisionTable({
  rows,
  loading,
}: {
  rows: TalByDivisionRow[]
  loading: boolean
}) {
  const tot = totalRow(rows)
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0}>
      <thead className="bg-[#F9FAFB] text-left text-[10px] uppercase tracking-wider text-[#6B7280]">
        <tr>
          <th className="px-3 py-2 font-semibold">Division</th>
          {AGG_HEADERS.map((h) => (
            <th key={h.key as string} className="px-3 py-2 text-right font-semibold">
              {h.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {tot && (
          <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
            <td className="px-3 py-2">Totals</td>
            <AggCells row={tot} />
          </tr>
        )}
        {rows.map((r) => (
          <tr key={r.division} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
            <td className="px-3 py-1.5 font-medium text-[#111827]">{r.division}</td>
            <AggCells row={r} />
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function CustomerTable({
  rows,
  loading,
}: {
  rows: TalByCustomerRow[]
  loading: boolean
}) {
  const tot = totalRow(rows)
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0}>
      <thead className="bg-[#F9FAFB] text-left text-[10px] uppercase tracking-wider text-[#6B7280]">
        <tr>
          <th className="px-3 py-2 font-semibold">Cust ID</th>
          {AGG_HEADERS.map((h) => (
            <th key={h.key as string} className="px-3 py-2 text-right font-semibold">
              {h.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {tot && (
          <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
            <td className="px-3 py-2">Totals</td>
            <AggCells row={tot} />
          </tr>
        )}
        {rows.map((r) => (
          <tr key={r.customer_id} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
            <td className="px-3 py-1.5 font-medium text-[#111827]">{r.customer_id}</td>
            <AggCells row={r} />
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function CustomerAwardTable({
  rows,
  loading,
}: {
  rows: TalByCustomerAwardRow[]
  loading: boolean
}) {
  const tot = totalRow(rows)
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0}>
      <thead className="bg-[#F9FAFB] text-left text-[10px] uppercase tracking-wider text-[#6B7280]">
        <tr>
          <th className="px-3 py-2 font-semibold">Cust Name</th>
          <th className="px-3 py-2 font-semibold">Award Name</th>
          <th className="px-3 py-2 font-semibold">Division</th>
          <th className="px-3 py-2 font-semibold">Status</th>
          {AGG_HEADERS.map((h) => (
            <th key={h.key as string} className="px-3 py-2 text-right font-semibold">
              {h.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {tot && (
          <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
            <td className="px-3 py-2" colSpan={4}>
              Totals
            </td>
            <AggCells row={tot} />
          </tr>
        )}
        {rows.map((r, i) => (
          <tr
            key={`${r.customer_name}-${r.award_name}-${i}`}
            className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
          >
            <td className="px-3 py-1.5 font-medium text-[#111827]">{r.customer_name}</td>
            <td className="max-w-[16rem] truncate px-3 py-1.5 text-[#374151]" title={r.award_name}>
              {r.award_name}
            </td>
            <td className="px-3 py-1.5 text-[#374151]">{r.division}</td>
            <td className="px-3 py-1.5">
              <StatusPill value={r.status} />
            </td>
            <AggCells row={r} />
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function AwardLaneTable({
  rows,
  loading,
  sort,
  setSort,
}: {
  rows: TalByAwardLaneRow[]
  loading: boolean
  sort: TalAwardLaneSort
  setSort: (s: TalAwardLaneSort) => void
}) {
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0}>
      <thead className="bg-[#F9FAFB] text-left text-[10px] uppercase tracking-wider text-[#6B7280]">
        <tr>
          <th className="px-3 py-2 font-semibold">Award ID</th>
          <th className="px-3 py-2 font-semibold">RFP Code</th>
          <SortableTh label="Award Name" k="award_asc" sort={sort} setSort={setSort} />
          <th className="px-3 py-2 font-semibold">Customer</th>
          <th className="px-3 py-2 font-semibold">Lane</th>
          <th className="px-3 py-2 font-semibold">Equip</th>
          <th className="px-3 py-2 font-semibold">Effective</th>
          <th className="px-3 py-2 font-semibold">Expiration</th>
          <SortableTh label="Days to Exp" k="days_asc" altK="days_desc" sort={sort} setSort={setSort} numeric />
          <th className="px-3 py-2 text-right font-semibold">Awarded Vol</th>
          <SortableTh label="Total Actual Vol" k="loads_desc" altK="loads_asc" sort={sort} setSort={setSort} numeric />
          <th className="px-3 py-2 text-right font-semibold" title="Δ in Total Actual Volume vs the snapshot ~7 days ago. Needs ≥7 days of n8n history.">WoW Δ</th>
          <SortableTh label="Load Variance" k="load_variance_desc" altK="load_variance_asc" sort={sort} setSort={setSort} numeric />
          <th className="px-3 py-2 text-right font-semibold">% Loads</th>
          <th className="px-3 py-2 text-right font-semibold">Projected Profit</th>
          <SortableTh label="Actual Profit" k="profit_desc" altK="profit_asc" sort={sort} setSort={setSort} numeric />
          <SortableTh label="Profit Variance" k="profit_variance_desc" altK="profit_variance_asc" sort={sort} setSort={setSort} numeric />
          <th className="px-3 py-2 text-right font-semibold">% Profit</th>
          <th className="px-3 py-2 text-right font-semibold">Projected CC</th>
          <SortableTh label="Actual CC" k="carrier_desc" altK="carrier_asc" sort={sort} setSort={setSort} numeric />
          <th className="px-3 py-2 text-right font-semibold">CC Variance</th>
          <th className="px-3 py-2 text-right font-semibold">% CC</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr
            key={`${r.audit_id ?? ""}-${r.lane}-${i}`}
            className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
          >
            <td className="px-3 py-1.5 text-[11px] tabular-nums text-[#6B7280]">{r.audit_id ?? "—"}</td>
            <td className="px-3 py-1.5 text-[11px] text-[#6B7280]">{r.award_id_name ?? "—"}</td>
            <td className="max-w-[14rem] truncate px-3 py-1.5 font-medium text-[#111827]" title={r.award_name}>
              {r.award_name}
            </td>
            <td className="max-w-[12rem] truncate px-3 py-1.5 text-[#374151]" title={r.customer_name}>
              {r.customer_name}
            </td>
            <td className="max-w-[14rem] truncate px-3 py-1.5 text-[#374151]" title={r.lane}>
              {r.lane}
            </td>
            <td className="px-3 py-1.5 text-[#374151]">{r.equip || "—"}</td>
            <td className="px-3 py-1.5 text-[#374151]">{fmtDate(r.effective_date)}</td>
            <td className="px-3 py-1.5 text-[#374151]">{fmtDate(r.expiration_date)}</td>
            <td className="px-3 py-1.5 text-right">
              <span
                className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${daysExpClass(
                  r.days_to_expiration,
                )}`}
              >
                {r.days_to_expiration == null ? "—" : r.days_to_expiration}
              </span>
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtInt(r.awarded_volume)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtInt(r.total_actual_volume)}</td>
            <td className="px-3 py-1.5 text-right">
              <WowCell delta={r.wow_delta_loads} prev={r.prev_total_loads} prevSnap={r.prev_snapshot} />
            </td>
            <td className={`px-3 py-1.5 text-right tabular-nums ${r.load_variance < 0 ? "text-[#991B1B]" : r.load_variance > 0 ? "text-[#065F46]" : ""}`}>
              {fmtSignedInt(r.load_variance)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-[#6B7280]">
              {r.load_ratio == null ? "—" : fmtPct(r.load_ratio)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.projected_profit)}</td>
            <td className={`px-3 py-1.5 text-right tabular-nums ${r.actual_profit < 0 ? "text-[#991B1B]" : ""}`}>
              {fmtMoney(r.actual_profit)}
            </td>
            <td className={`px-3 py-1.5 text-right tabular-nums ${r.profit_variance < 0 ? "text-[#991B1B]" : r.profit_variance > 0 ? "text-[#065F46]" : ""}`}>
              {fmtSignedMoney(r.profit_variance)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-[#6B7280]">
              {r.profit_ratio == null ? "—" : fmtPct(r.profit_ratio)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.projected_carrier_cost)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.actual_carrier_cost)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtSignedMoney(r.carrier_cost_variance)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-[#6B7280]">
              {r.carrier_cost_ratio == null ? "—" : fmtPct(r.carrier_cost_ratio)}
            </td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------

function StatusPill({ value }: { value: string }) {
  const v = (value || "").toLowerCase()
  const cls =
    v === "active"
      ? "bg-[#D1FAE5] text-[#065F46]"
      : v === "expired"
        ? "bg-[#FEE2E2] text-[#991B1B]"
        : "bg-[#F3F4F6] text-[#6B7280]"
  return (
    <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${cls}`}>
      {value || "—"}
    </span>
  )
}

function SortableTh({
  label,
  k,
  altK,
  sort,
  setSort,
  numeric,
}: {
  label: string
  k: TalAwardLaneSort
  altK?: TalAwardLaneSort
  sort: TalAwardLaneSort
  setSort: (s: TalAwardLaneSort) => void
  numeric?: boolean
}) {
  const active = sort === k || sort === altK
  const onClick = () => {
    if (sort === k && altK) setSort(altK)
    else setSort(k)
  }
  return (
    <th className={`px-3 py-2 font-semibold ${numeric ? "text-right" : ""}`}>
      <button
        onClick={onClick}
        className={`inline-flex items-center gap-1 ${active ? "text-[#111827]" : "text-[#6B7280]"} hover:text-[#111827]`}
      >
        {label}
        <ArrowUpDown className="h-3 w-3" />
      </button>
    </th>
  )
}

// ---------------------------------------------------------------------------
// WoW cell — colored arrow + delta value, em-dash before history exists
// ---------------------------------------------------------------------------

function WowCell({
  delta,
  prev,
  prevSnap,
}: {
  delta: number | null
  prev: number | null
  prevSnap: string | null
}) {
  if (delta == null || prev == null) {
    return (
      <span className="text-[10px] text-[#9CA3AF]" title="No prior snapshot — needs ≥7 days of n8n history">
        —
      </span>
    )
  }
  const tone =
    delta > 0
      ? "text-[#065F46]"
      : delta < 0
        ? "text-[#991B1B]"
        : "text-[#6B7280]"
  const Arrow = delta > 0 ? ArrowUp : delta < 0 ? ArrowDown : Minus
  const tooltip = `Prev (${prevSnap?.slice(0, 10) ?? "—"}): ${prev.toLocaleString("en-US")}`
  return (
    <span className={`inline-flex items-center justify-end gap-0.5 text-xs tabular-nums ${tone}`} title={tooltip}>
      <Arrow className="h-3 w-3" />
      <span>{delta === 0 ? "0" : (delta > 0 ? "+" : "") + Math.round(delta).toLocaleString("en-US")}</span>
    </span>
  )
}

function fmtSignedInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  if (n === 0) return "0"
  return (n > 0 ? "+" : "") + Math.round(n).toLocaleString("en-US")
}

function fmtSignedMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  if (n === 0) return "$0"
  const formatted = Math.abs(n).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
  return (n > 0 ? "+" : "-") + formatted
}

function parseList(v: string | null): string[] {
  if (!v) return []
  return v.split(",").map((x) => x.trim()).filter(Boolean)
}

// ---------------------------------------------------------------------------
// Expiry banner — surfaces awards expiring soon AND underperforming
// ---------------------------------------------------------------------------

function ExpiryBanner({
  rows,
  loading,
  onJumpToDeepest,
}: {
  rows: TalByAwardLaneRow[]
  loading: boolean
  onJumpToDeepest: () => void
}) {
  // Look only at Active awards. Underperforming = % loads ratio < 80% OR
  // actual_profit < projected_profit (whichever is more conservative).
  const summary = useMemo(() => {
    let exp7 = 0
    let exp30 = 0
    let exp7Bad = 0
    for (const r of rows) {
      if (r.days_to_expiration == null || r.days_to_expiration < 0) continue
      const underperforming =
        (r.load_ratio != null && r.load_ratio < 0.8) ||
        r.actual_profit < r.projected_profit
      if (r.days_to_expiration <= 7) {
        exp7 += 1
        if (underperforming) exp7Bad += 1
      }
      if (r.days_to_expiration <= 30) exp30 += 1
    }
    return { exp7, exp30, exp7Bad }
  }, [rows])

  if (loading || rows.length === 0 || (summary.exp7 === 0 && summary.exp30 === 0)) {
    return null
  }

  const tone =
    summary.exp7 > 0
      ? {
          bg: "bg-[#FEF2F2]",
          border: "border-[#FCA5A5]",
          icon: "text-[#991B1B]",
          headline: "text-[#991B1B]",
          dim: "text-[#7F1D1D]",
        }
      : {
          bg: "bg-[#FEFCE8]",
          border: "border-[#FEF08A]",
          icon: "text-[#92400E]",
          headline: "text-[#92400E]",
          dim: "text-[#78350F]",
        }

  return (
    <button
      onClick={onJumpToDeepest}
      className={`group flex w-full items-start gap-3 rounded-lg border ${tone.border} ${tone.bg} px-4 py-3 text-left transition-shadow hover:shadow-md`}
    >
      <AlertCircle className={`mt-0.5 h-5 w-5 shrink-0 ${tone.icon}`} />
      <div className="flex-1 space-y-0.5">
        <div className={`text-sm font-semibold ${tone.headline}`}>
          {summary.exp7 > 0
            ? `${summary.exp7} award lane${summary.exp7 === 1 ? "" : "s"} expire in ≤ 7 days`
            : `${summary.exp30} award lane${summary.exp30 === 1 ? "" : "s"} expire in ≤ 30 days`}
          {summary.exp7Bad > 0 && (
            <span className="ml-2 rounded-full bg-[#991B1B] px-2 py-0.5 text-[10px] uppercase tracking-wider text-white">
              {summary.exp7Bad} underperforming
            </span>
          )}
        </div>
        <div className={`text-xs ${tone.dim}`}>
          ≤7d: <strong>{summary.exp7}</strong> · ≤30d: <strong>{summary.exp30}</strong>
          {" "}— click to jump to the Award &amp; Lane table sorted by Days to Exp ↑
        </div>
      </div>
      <span className={`shrink-0 self-center text-xs font-semibold ${tone.headline} group-hover:underline`}>
        View →
      </span>
    </button>
  )
}
