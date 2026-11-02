/**
 * The TV rendering of one Rank table. Server component, no hooks, no state:
 * large type, high contrast, read from across a room. Columns mirror the
 * report's Rank tab (`app/reports/booker-performance-scorecard/RankTable.tsx`).
 */
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  type PublicRankRow,
  type PublicRankTable,
} from "@/lib/public-display-format"

function Movement({ delta }: { delta: number | null }) {
  // ⚠ null = absent from the comparison window: "new", never a flat 0.
  if (delta === null) return <span className="text-base font-medium text-[#6B7280]">new</span>
  if (delta === 0) return <span className="text-base text-[#9CA3AF]">— 0</span>
  const up = delta > 0
  return (
    <span className={`text-lg font-bold ${up ? "text-[#15803D]" : "text-[#B91C1C]"}`}>
      {up ? "▲" : "▼"} {Math.abs(delta)}
    </span>
  )
}

function Row({ r, total }: { r: PublicRankRow; total: number }) {
  return (
    <tr className="border-b border-[#E5E7EB] last:border-0 even:bg-[#F9FAFB]">
      <td className="whitespace-nowrap px-4 py-2">
        <span className="text-2xl font-bold text-[#111827]">{r.rank ?? "—"}</span>
        <span className="text-sm text-[#9CA3AF]"> of {total}</span>
        <span className="ml-3">
          <Movement delta={r.rank_delta} />
        </span>
      </td>
      <td className="px-4 py-2 text-xl font-semibold text-[#111827]">{r.booker}</td>
      <td className="px-4 py-2 text-right text-xl">
        {fmtPct(r.compliance_threshold_pct)}
        {r.compliance_threshold_pct !== null && (
          <span className="ml-2 text-sm text-[#9CA3AF]">
            ({fmtCount(r.compliant_threshold)}/{fmtCount(r.threshold_orders)})
          </span>
        )}
      </td>
      <td className="px-4 py-2 text-right text-xl">{fmtUsd(r.cost_saving)}</td>
      <td className="px-4 py-2 text-right text-xl font-semibold text-[#111827]">
        {fmtCount(r.bookings)}
        <span className="ml-2 text-sm font-normal text-[#9CA3AF]">
          (prev {fmtCount(r.prev_bookings)})
        </span>
      </td>
    </tr>
  )
}

interface Props {
  title: string
  caption: string
  table: PublicRankTable
  emptyText: string
}

export function RankBoard({ title, caption, table, emptyText }: Props) {
  return (
    <section className="overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <header className="flex items-baseline justify-between gap-4 border-b border-[#E5E7EB] bg-[#1B3A5C] px-5 py-3">
        <h2 className="text-2xl font-bold text-white">{title}</h2>
        <p className="text-base text-[#CBD5E1]">{caption}</p>
      </header>
      <table className="w-full">
        <thead className="border-b border-[#E5E7EB] bg-[#F3F4F6] text-left text-sm uppercase tracking-wide text-[#4B5563]">
          <tr>
            <th className="px-4 py-2">Rank</th>
            <th className="px-4 py-2">Booker Name</th>
            <th className="px-4 py-2 text-right">Compliance Threshold</th>
            <th className="px-4 py-2 text-right">Cost Saving</th>
            <th className="px-4 py-2 text-right"># of Bookings</th>
          </tr>
        </thead>
        <tbody>
          {table.rows.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-4 py-10 text-center text-xl text-[#6B7280]">
                {emptyText}
              </td>
            </tr>
          ) : (
            table.rows.map((r) => <Row key={r.booker} r={r} total={table.total_bookers} />)
          )}
        </tbody>
      </table>
    </section>
  )
}
