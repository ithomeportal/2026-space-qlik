"use client"

import { useEffect, useState } from "react"
import { Loader2, Plus, Save, Trash2, Truck } from "lucide-react"
import {
  useCarrierSalesEntries,
  useCreateCarrierSales,
  useDeleteCarrierSales,
  useUpdateCarrierSales,
  type KamCarrierSalesEntry,
} from "@/lib/kam-performance-dfw-api"

// Bruno PDF 2026-07-20: Carrier Sales is now a fully MANUAL table — no
// datalake auto-populate. The KAM enters every column by hand and Saves each
// row. Rows are private (per-user).
export function Tab7CarrierSales() {
  const { data, isLoading } = useCarrierSalesEntries()
  const create = useCreateCarrierSales()
  const update = useUpdateCarrierSales()
  const remove = useDeleteCarrierSales()
  const rows = data?.data ?? []

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-1 flex items-center gap-2">
          <Truck className="h-4 w-4 text-[#1B3A5C]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">Carrier Sales</div>
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Enter carrier intel per lane by hand — lane, carrier, cost, moves and
          comments. Per-user: only you can see and edit your rows.
        </p>
        <button
          onClick={() => create.mutate({})}
          disabled={create.isPending}
          className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-3 py-1.5 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-50"
        >
          {create.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          Add row
        </button>
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <th className="px-2 py-1.5 text-left">Lane</th>
                <th className="px-2 py-1.5 text-left">Carrier</th>
                <th className="px-2 py-1.5 text-right">Cost</th>
                <th className="px-2 py-1.5 text-right">Moves</th>
                <th className="px-2 py-1.5 text-left">Comments</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-[#9CA3AF]">
                    No rows yet — use “Add row” to start.
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <CarrierRow
                    key={r.id}
                    row={r}
                    onSave={(patch) => update.mutateAsync({ id: r.id, ...patch })}
                    onDelete={() => remove.mutate(r.id)}
                    savePending={update.isPending}
                    deletePending={remove.isPending}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div className="text-[10px] text-[#6B7280]">
        Manual entry · per-user scratchpad
      </div>
    </div>
  )
}

function CarrierRow({
  row,
  onSave,
  onDelete,
  savePending,
  deletePending,
}: {
  row: KamCarrierSalesEntry
  onSave: (patch: {
    lane?: string
    carrier?: string
    cost?: number | null
    cost_set?: boolean
    moves?: number | null
    moves_set?: boolean
    comments?: string
  }) => Promise<unknown>
  onDelete: () => void
  savePending: boolean
  deletePending: boolean
}) {
  const [lane, setLane] = useState(row.lane)
  const [carrier, setCarrier] = useState(row.carrier)
  const [cost, setCost] = useState(row.cost == null ? "" : String(row.cost))
  const [moves, setMoves] = useState(row.moves == null ? "" : String(row.moves))
  const [comments, setComments] = useState(row.comments)

  useEffect(() => {
    setLane(row.lane)
    setCarrier(row.carrier)
    setCost(row.cost == null ? "" : String(row.cost))
    setMoves(row.moves == null ? "" : String(row.moves))
    setComments(row.comments)
  }, [row.id, row.lane, row.carrier, row.cost, row.moves, row.comments])

  const costNum = cost.trim() === "" ? null : Number(cost)
  const movesNum = moves.trim() === "" ? null : Number(moves)
  const dirty =
    lane !== row.lane ||
    carrier !== row.carrier ||
    costNum !== row.cost ||
    movesNum !== row.moves ||
    comments !== row.comments
  const invalid =
    (cost.trim() !== "" && Number.isNaN(costNum)) ||
    (moves.trim() !== "" && (Number.isNaN(movesNum) || (movesNum ?? 0) < 0))

  const doSave = () =>
    onSave({
      lane: lane.trim(),
      carrier: carrier.trim(),
      cost: costNum,
      cost_set: true,
      moves: movesNum,
      moves_set: true,
      comments,
    })

  return (
    <tr className="border-b border-[#F3F4F6] align-top last:border-0">
      <td className="px-2 py-2">
        <input
          value={lane}
          onChange={(e) => setLane(e.target.value)}
          placeholder="Origin - Destination"
          className="w-44 rounded-md border border-[#E5E7EB] bg-white px-1.5 py-1 text-xs"
        />
      </td>
      <td className="px-2 py-2">
        <input
          value={carrier}
          onChange={(e) => setCarrier(e.target.value)}
          placeholder="Carrier"
          className="w-44 rounded-md border border-[#E5E7EB] bg-white px-1.5 py-1 text-xs"
        />
      </td>
      <td className="px-2 py-2 text-right">
        <input
          value={cost}
          onChange={(e) => setCost(e.target.value)}
          inputMode="decimal"
          placeholder="0"
          className="w-24 rounded-md border border-[#E5E7EB] bg-white px-1.5 py-1 text-right text-xs tabular-nums"
        />
      </td>
      <td className="px-2 py-2 text-right">
        <input
          value={moves}
          onChange={(e) => setMoves(e.target.value)}
          inputMode="numeric"
          placeholder="0"
          className="w-16 rounded-md border border-[#E5E7EB] bg-white px-1.5 py-1 text-right text-xs tabular-nums"
        />
      </td>
      <td className="px-2 py-2">
        <textarea
          rows={2}
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="Comments…"
          className="w-56 rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-1.5 text-xs"
        />
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center gap-1.5">
          <button
            onClick={doSave}
            disabled={!dirty || invalid || savePending}
            className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-2.5 py-1 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-40"
          >
            {savePending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Save className="h-3 w-3" />
            )}
            Save
          </button>
          <button
            onClick={onDelete}
            disabled={deletePending}
            className="rounded p-1.5 text-[#9CA3AF] hover:bg-[#FEE2E2] hover:text-[#991B1B] disabled:opacity-30"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </td>
    </tr>
  )
}
