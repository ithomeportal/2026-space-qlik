"use client"

import { Suspense, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Loader2, MailCheck } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { useCustomerEmailActivity } from "@/lib/customer-status-email-api"
import { TodayGrid } from "./TodayGrid"
import { ActivityTable } from "./ActivityTable"

const WINDOWS = [1, 7, 30, 90] as const
const REPORTS = [
  { k: null, label: "All e-mails" },
  { k: "pca-donna", label: "DONNA" },
  { k: "pca-laredo", label: "LAREDO" },
  { k: "pca-el-paso", label: "EL PASO" },
  { k: "pca-reynosa", label: "REYNOSA" },
] as const

function ModeChip({ live, enabled }: { live: boolean; enabled: boolean }) {
  if (!enabled) {
    return <span className="rounded-full bg-red-100 px-2.5 py-1 text-xs text-red-800">Sending DISABLED</span>
  }
  return live ? (
    <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs text-green-800">LIVE — sending to customers</span>
  ) : (
    <span
      className="rounded-full bg-amber-100 px-2.5 py-1 text-xs text-amber-800"
      title="Every e-mail goes to Jaime Anaya (CC t1ops, BCC dfrodriguez) until go-live"
    >
      TEST mode — customers receive nothing yet
    </span>
  )
}

function Content() {
  const [days, setDays] = useState<number>(7)
  const [report, setReport] = useState<string | null>(null)
  const { data, isLoading, error } = useCustomerEmailActivity(days, report)

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
          <MailCheck className="h-5 w-5 text-slate-400" />
          <div>
            <h1 className="text-lg font-semibold text-slate-900">Customer E-mail Activity</h1>
            <p className="text-xs text-slate-500">
              Automated PCA load-status e-mails: what went out, when, to whom and with how many loads.
            </p>
          </div>
        </div>
        {data && <ModeChip live={data.live} enabled={data.enabled} />}
      </div>

      {isLoading && (
        <div className="flex h-40 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
      )}
      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Could not load the e-mail activity.
        </div>
      ) : null}

      {data && <TodayGrid today={data.today} />}

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex gap-1 rounded-md border border-slate-200 p-0.5">
          {WINDOWS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded px-2.5 py-1 text-xs ${days === d ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {d === 1 ? "Last 24h" : `Last ${d} days`}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1 rounded-md border border-slate-200 p-0.5">
          {REPORTS.map((r) => (
            <button
              key={r.label}
              onClick={() => setReport(r.k)}
              className={`rounded px-2.5 py-1 text-xs ${report === r.k ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {r.label}
            </button>
          ))}
        </div>
        {data && <span className="text-xs text-slate-500">{data.rows.length} e-mail(s)</span>}
      </div>

      {data && <ActivityTable rows={data.rows} />}
    </div>
  )
}

export default function Page() {
  return (
    <ReportGuard reportKey="customer-status-email">
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
