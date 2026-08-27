"use client"

import { Suspense, useState } from "react"
import Link from "next/link"
import { ArrowLeft, FileInput, Loader2 } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { MultiSelectChips } from "@/components/MultiSelectChips"
import {
  useEdiByCustomer,
  useEdiChart,
  useEdiExceptions,
  useEdiFilterOptions,
  useEdiFreshness,
  useEdiSummary,
  type EdiFilters,
  type EdiGrain,
  type EdiPurpose,
  type EdiRange,
} from "@/lib/edi-load-tenders-api"
import { KpiCards } from "./KpiCards"
import { TrendChart } from "./TrendChart"
import { CustomerTable } from "./CustomerTable"
import { ExceptionBoard } from "./ExceptionBoard"

const RANGES: { k: EdiRange; label: string }[] = [
  { k: "mtd", label: "Month to Date" },
  { k: "l30", label: "Last 30d" },
  { k: "l90", label: "Last 90d" },
  { k: "ytd", label: "Year to Date" },
  { k: "all", label: "All time" },
  { k: "custom", label: "Custom" },
]

const PURPOSES: EdiPurpose[] = ["ORIGINAL", "CHANGE", "CANCEL"]
const PURPOSE_LABELS: Record<string, string> = {
  ORIGINAL: "Original",
  CHANGE: "Change",
  CANCEL: "Cancellation",
}

function FreshnessChip() {
  const { data } = useEdiFreshness()
  if (!data?.received) return null
  const stamp = data.received.slice(0, 16).replace("T", " ")
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs ${
        data.is_stale
          ? "bg-red-100 text-red-800"
          : "bg-slate-100 text-slate-600"
      }`}
      title="MAX(received) — an EDI event time, not an ETL load time"
    >
      Data as of {stamp} CST
      {data.is_stale ? " · feed looks stalled" : ""}
    </span>
  )
}

function Content() {
  const [range, setRange] = useState<EdiRange>("l90")
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [customer, setCustomer] = useState<string[]>([])
  const [purpose, setPurpose] = useState<EdiPurpose[]>([])
  const [team, setTeam] = useState<string[]>([])
  const [grain, setGrain] = useState<EdiGrain>("week")
  const [liveOnly, setLiveOnly] = useState(true)

  const filters: EdiFilters = { range, startDate, endDate, customer, purpose, team }

  const options = useEdiFilterOptions()
  const summary = useEdiSummary(filters)
  const chart = useEdiChart(filters, grain)
  const byCustomer = useEdiByCustomer(filters)
  const exceptions = useEdiExceptions(filters, liveOnly)

  const customerOptions = (options.data?.customers ?? []).map((c) => c.value)
  const customerLabels = Object.fromEntries(
    (options.data?.customers ?? []).map((c) => [c.value, c.label]),
  )

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <FileInput className="h-5 w-5 text-slate-400" />
          <div>
            <h1 className="text-lg font-semibold text-slate-900">EDI Load Tenders</h1>
            <p className="text-xs text-slate-500">
              What our EDI partners tendered, what we turned into an order, and what
              got cancelled on either side.
            </p>
          </div>
        </div>
        <FreshnessChip />
      </div>

      {/* filter strip */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex gap-1 rounded-md border border-slate-200 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.k}
              onClick={() => setRange(r.k)}
              className={`rounded px-2.5 py-1 text-xs ${
                range === r.k
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>

        {range === "custom" ? (
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={startDate}
              min={options.data?.data_floor}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-md border border-slate-200 px-2 py-1 text-xs"
            />
            <span className="text-xs text-slate-400">to</span>
            <input
              type="date"
              value={endDate}
              min={options.data?.data_floor}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-md border border-slate-200 px-2 py-1 text-xs"
            />
          </div>
        ) : null}

        <MultiSelectChips
          label="Customer"
          options={customerOptions}
          selected={customer}
          onChange={setCustomer}
          optionLabels={customerLabels}
          width={260}
        />
        <MultiSelectChips
          label="Purpose"
          options={PURPOSES}
          selected={purpose}
          onChange={(v) => setPurpose(v as EdiPurpose[])}
          optionLabels={PURPOSE_LABELS}
          width={180}
        />
        <MultiSelectChips
          label="Team"
          options={options.data?.teams ?? []}
          selected={team}
          onChange={setTeam}
          width={180}
        />

        {summary.isFetching ? (
          <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
        ) : null}
      </div>

      {summary.data?.team_filtered ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          A team filter is applied. Team is only known for tenders we turned into an
          order, so &ldquo;Never created&rdquo; cannot be counted under this scope and
          reads <span className="font-medium">n/a</span> rather than zero.
        </p>
      ) : null}

      <KpiCards data={summary.data} />

      <ExceptionBoard
        rows={exceptions.data?.rows ?? []}
        totalCharge={exceptions.data?.totalCharge ?? 0}
        truncated={exceptions.data?.truncated ?? false}
        liveOnly={liveOnly}
        onLiveOnlyChange={setLiveOnly}
        loading={exceptions.isLoading}
      />

      <TrendChart
        data={chart.data ?? []}
        grain={grain}
        onGrainChange={setGrain}
        loading={chart.isLoading}
      />

      <CustomerTable rows={byCustomer.data ?? []} loading={byCustomer.isLoading} />

      <p className="pb-4 text-xs leading-relaxed text-slate-400">
        Counted at shipment grain: one shipment carries an original tender, any number
        of changes, and possibly a cancellation, so counting EDI messages would inflate
        volume by about three quarters. &ldquo;Order created&rdquo; is derived from the
        order id actually present on the tender — the feed&apos;s own status column is
        99.99% <span className="font-mono">ACCEPTED</span> and carries no signal.
        Source: <span className="font-mono">mcleod_gld_edi_load_tender</span>, re-ingested
        roughly every 10 minutes.
      </p>
    </div>
  )
}

export default function Page() {
  return (
    <ReportGuard reportKey="edi-load-tenders">
      <Suspense
        fallback={
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        }
      >
        <Content />
      </Suspense>
    </ReportGuard>
  )
}
