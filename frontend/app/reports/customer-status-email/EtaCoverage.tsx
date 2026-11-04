import { Loader2 } from "lucide-react"
import {
  useEtaCoverage,
  type CoverageMissing,
  type CoverageReport,
  type CoverageTrendDay,
} from "@/lib/customer-status-email-api"
import { fmtCst } from "./StatusBadge"

const percent = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : 0)

function issue(load: CoverageMissing): string {
  return load.etaPassed ? `ETA passed ${fmtCst(load.etaPassed)}` : "No ETA keyed"
}

function shownInstead(load: CoverageMissing): string {
  if (load.shownInstead === "augie") return "Augie ETA"
  if (load.shownInstead === "estimate") return "Calculated estimate"
  return "ETA pending"
}

function ReportTile({ report }: { report: CoverageReport }) {
  const share = percent(report.keyed, report.open)
  return (
    <div className="rounded-md border border-slate-200 p-3">
      <div className="truncate text-xs text-slate-500" title={report.subject}>{report.subject}</div>
      <div className="mt-1 text-xl font-semibold text-slate-900">
        {report.keyed} <span className="text-sm font-normal text-slate-500">of {report.open} loads</span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"
        title={`ETA keyed on ${report.keyed} of ${report.open} loads on their way (${share}%)`}
      >
        <div className="h-full rounded-full bg-blue-600" style={{ width: `${share}%` }} />
      </div>
      <div className="mt-1.5 text-[11px] text-slate-500">
        {report.inProgress - report.open} arrived · {report.estimated} estimated · {report.augie} from Augie
      </div>
    </div>
  )
}

/** One entry per day, summed over the reports on screen. */
function byDay(rows: CoverageTrendDay[], reports: CoverageReport[]) {
  const shown = new Set(reports.map((r) => r.key))
  const days = rows.filter((r) => shown.has(r.report)).map((r) => r.day)
  return Array.from(new Set(days)).map((day) => {
    const same = rows.filter((r) => r.day === day && shown.has(r.report))
    return {
      day,
      keyed: same.reduce((sum, r) => sum + r.keyed, 0),
      open: same.reduce((sum, r) => sum + r.open, 0),
    }
  })
}

function Trend({ rows, reports }: { rows: CoverageTrendDay[]; reports: CoverageReport[] }) {
  const days = byDay(rows, reports)
  if (days.length === 0) {
    return <p className="px-4 pb-3 text-xs text-slate-500">The daily trend starts with the next scheduled send.</p>
  }
  return (
    <div className="flex flex-wrap gap-2 px-4 pb-3">
      {days.slice(-10).map((d) => (
        <div
          key={d.day}
          className="rounded border border-slate-200 px-2 py-1 text-center"
          title={`${d.keyed} of ${d.open} load appearances across that day's sends`}
        >
          <div className="text-[10px] text-slate-500">{d.day.slice(5).replace("-", "/")}</div>
          <div className="text-xs font-semibold text-slate-800">{percent(d.keyed, d.open)}%</div>
        </div>
      ))}
    </div>
  )
}

function MissingTable({ reports }: { reports: CoverageReport[] }) {
  const rows = reports.flatMap((r) => r.missing.map((load) => ({ report: r.subject, load })))
  if (rows.length === 0) {
    const anyOpen = reports.some((r) => r.open > 0)
    return (
      <p className="px-4 pb-4 text-sm text-slate-600">
        {anyOpen ? "Every load on its way has an ETA keyed." : "No loads on their way right now."}
      </p>
    )
  }
  return (
    <div className="overflow-x-auto border-t border-slate-200">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-3 py-2 font-medium">Load</th>
            <th className="px-3 py-2 font-medium">UNILINK#</th>
            <th className="px-3 py-2 font-medium">Consignee</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Delivery appt.</th>
            <th className="px-3 py-2 font-medium">To fix in McLeod</th>
            <th className="px-3 py-2 font-medium">Card shows now</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(({ report, load }) => (
            <tr key={load.orderId} title={report}>
              <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-900">{load.po ?? "—"}</td>
              <td className="px-3 py-2 text-slate-700">{load.orderId}</td>
              <td className="px-3 py-2 text-slate-700">{load.consignee ?? "—"}</td>
              <td className="px-3 py-2 text-slate-700">{load.status ?? "—"}</td>
              <td className="whitespace-nowrap px-3 py-2 text-slate-700">
                {load.deliveryAppt ? fmtCst(load.deliveryAppt) : "—"}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-slate-800">{issue(load)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-slate-700">{shownInstead(load)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** ETA keyed in McLeod on X of Y loads on their way, and the loads to key next. */
export function EtaCoverage({ report }: { report: string | null }) {
  const { data, isLoading, error } = useEtaCoverage()
  const visible = data?.reports.filter((r) => report === null || r.key === report) ?? []
  const keyed = visible.reduce((sum, r) => sum + r.keyed, 0)
  const open = visible.reduce((sum, r) => sum + r.open, 0)

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">ETA coverage</h2>
          <p className="text-xs text-slate-500">
            ETA keyed on the final stop in McLeod, for loads on their way. Only a keyed ETA counts here.
            Load times below are local to each stop.
          </p>
        </div>
        {data && (
          <div className="text-right">
            <div className="text-sm font-semibold text-slate-900">
              ETA filled on {keyed} of {open} loads
            </div>
            <div className="text-[11px] text-slate-500">Data as of {fmtCst(data.asOf)} CST</div>
          </div>
        )}
      </div>
      {isLoading && (
        <div className="flex h-24 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
      )}
      {error ? (
        <p className="px-4 pb-4 text-sm text-red-800">Could not load ETA coverage. The e-mails are not affected.</p>
      ) : null}
      {data && (
        <>
          <div className="grid gap-3 px-4 pb-3 sm:grid-cols-2 xl:grid-cols-4">
            {visible.map((r) => <ReportTile key={r.key} report={r} />)}
          </div>
          <Trend rows={data.trend} reports={visible} />
          <MissingTable reports={visible} />
        </>
      )}
    </section>
  )
}
