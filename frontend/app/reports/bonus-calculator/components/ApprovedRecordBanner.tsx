import { Lock, TriangleAlert } from "lucide-react"
import type { BonusReport } from "@/lib/bonus-api"
import { usd } from "../format"

const APPROVED_DATE = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "America/Chicago",
})

function signedUsd(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(Math.abs(n))}`
}

/** Says whether a locked month shows the figures stored at approval or live ones. */
export function ApprovedRecordBanner({ report }: { report: BonusReport }) {
  const record = report.approvedRecord
  if (record) {
    const approvedOn = record.approvedAt ? APPROVED_DATE.format(new Date(record.approvedAt)) : "date unknown"
    return (
      <section className="flex items-start gap-2 rounded-2xl border border-[#BBF7D0] bg-[#F0FDF4] px-5 py-3 text-sm text-[#166534]">
        <Lock className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <p className="font-semibold">
            Approved figures, {approvedOn} CST{record.approvedBy ? ` by ${record.approvedBy}` : ""}
          </p>
          <p className="text-xs">
            Stored when this month was approved, so later load changes do not move them.{" "}
            {record.liveTotalUsd == null || record.differenceUsd == null
              ? "The comparison with live data is unavailable right now."
              : `Live data today: ${usd(record.liveTotalUsd)} (${signedUsd(record.differenceUsd)} against the approved ${usd(record.approvedTotalUsd)}).`}
          </p>
        </div>
      </section>
    )
  }
  if (report.lock.status !== "approved") return null
  return (
    <section className="flex items-start gap-2 rounded-2xl border border-[#FDE68A] bg-[#FFFBEB] px-5 py-3 text-sm text-[#92400E]">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-semibold">Live figures, no approved record</p>
        <p className="text-xs">
          This month was locked before Space stored approved figures. It recalculates from current load data and can
          differ from what was paid.
        </p>
      </div>
    </section>
  )
}
