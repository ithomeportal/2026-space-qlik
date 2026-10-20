import { ExternalLink } from "lucide-react"
import { previewUrl, type TodayReport } from "@/lib/customer-status-email-api"
import { StatusBadge, fmtCst, fmtHour } from "./StatusBadge"

/** Today's schedule: every report × send hour, including slots that never ran. */
export function TodayGrid({ today }: { today: TodayReport[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold text-slate-800">
        Today&apos;s schedule (CST)
      </div>
      <div className="divide-y divide-slate-100">
        {today.map((r) => (
          <div key={r.key} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="w-56 shrink-0">
              <div className="text-sm font-medium text-slate-900">{r.subject}</div>
              <a
                href={previewUrl(r.key)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-blue-700 hover:underline"
              >
                Preview now <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            <div className="flex flex-wrap gap-2">
              {r.slots.map((s) => (
                <div
                  key={s.hour}
                  className="flex min-w-[96px] flex-col items-center rounded-md border border-slate-200 px-2 py-1.5"
                  title={s.sentAt ? `Finished ${fmtCst(s.sentAt)} CST` : undefined}
                >
                  <span className="text-xs font-semibold text-slate-700">{fmtHour(s.hour)}</span>
                  <StatusBadge status={s.status} />
                  {s.sentAt && (
                    <span className="mt-0.5 text-[10px] text-slate-500">{fmtCst(s.sentAt).slice(6)}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
