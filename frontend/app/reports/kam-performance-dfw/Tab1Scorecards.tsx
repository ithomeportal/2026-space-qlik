"use client"

import { useState } from "react"
import { Loader2, Plus, Trash2 } from "lucide-react"
import {
  useCreateScorecard,
  useDeleteScorecard,
  useKamScorecards,
} from "@/lib/kam-performance-dfw-api"
import { fmtDate } from "./format"

const FREQUENCIES = ["Weekly", "Bi-Weekly", "Monthly", "Quarterly", "Yearly", "Ad-hoc"]

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export function Tab1Scorecards() {
  const { data, isLoading } = useKamScorecards()
  const create = useCreateScorecard()
  const remove = useDeleteScorecard()

  const [customer, setCustomer] = useState("")
  const [scorecardDate, setScorecardDate] = useState(todayIso())
  const [frequency, setFrequency] = useState(FREQUENCIES[0])
  const [err, setErr] = useState<string | null>(null)

  const rows = data?.data ?? []

  const onAdd = async () => {
    setErr(null)
    if (!customer.trim()) {
      setErr("Customer is required")
      return
    }
    try {
      await create.mutateAsync({
        customer: customer.trim(),
        scorecard_date: scorecardDate,
        scorecard_frequency: frequency,
      })
      setCustomer("")
      setScorecardDate(todayIso())
      setFrequency(FREQUENCIES[0])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save")
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-2 text-sm font-semibold text-[#1B3A5C]">
          Log a scorecard sent
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Per-user log — only you see the entries you add. The upload timestamp
          (created_at) is recorded automatically.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <input
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
              placeholder="Customer name"
              className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              Scorecard date
            </label>
            <input
              type="date"
              value={scorecardDate}
              onChange={(e) => setScorecardDate(e.target.value)}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              Frequency
            </label>
            <select
              value={frequency}
              onChange={(e) => setFrequency(e.target.value)}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
            >
              {FREQUENCIES.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={onAdd}
            disabled={create.isPending}
            className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-3 py-1.5 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-50"
          >
            {create.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Save
          </button>
          {err && <span className="text-xs text-[#991B1B]">{err}</span>}
        </div>
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-2 text-sm font-semibold text-[#1B3A5C]">
          My scorecard log
        </div>
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <th className="px-2 py-1.5 text-left">Customer</th>
                <th className="px-2 py-1.5 text-left">Scorecard date</th>
                <th className="px-2 py-1.5 text-left">Frequency</th>
                <th className="px-2 py-1.5 text-left">Uploaded at</th>
                <th className="px-2 py-1.5 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-[#9CA3AF]">
                    No scorecards logged yet.
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-[#F3F4F6] last:border-0"
                  >
                    <td className="px-2 py-1.5">{r.customer}</td>
                    <td className="px-2 py-1.5">{fmtDate(r.scorecard_date)}</td>
                    <td className="px-2 py-1.5">{r.scorecard_frequency}</td>
                    <td className="px-2 py-1.5 text-[#6B7280]">
                      {fmtDate(r.created_at)}
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <button
                        onClick={() => remove.mutate(r.id)}
                        disabled={remove.isPending}
                        className="rounded p-1 text-[#9CA3AF] hover:bg-[#FEE2E2] hover:text-[#991B1B] disabled:opacity-30"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
