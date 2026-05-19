"use client"

import { useState } from "react"
import { Loader2, Plus, Save, Trash2 } from "lucide-react"
import {
  useCreateCustomerDev,
  useCustomerDev,
  useDeleteCustomerDev,
  useUpdateCustomerDev,
  type KamCustomerDevRow,
} from "@/lib/kam-performance-dfw-api"

export function Tab4CustomerDev() {
  const { data, isLoading } = useCustomerDev()
  const create = useCreateCustomerDev()
  const update = useUpdateCustomerDev()
  const remove = useDeleteCustomerDev()

  const [newName, setNewName] = useState("")
  const rows = data?.data ?? []

  const onAdd = async () => {
    if (!newName.trim()) return
    await create.mutateAsync({ contact_name: newName.trim() })
    setNewName("")
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-2 text-sm font-semibold text-[#1B3A5C]">
          Customer development
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Track conversations and concrete action plans per contact. Per-user —
          only you can see and edit your rows.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Contact name"
            className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
          />
          <button
            onClick={onAdd}
            disabled={create.isPending || !newName.trim()}
            className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-3 py-1.5 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-50"
          >
            {create.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Add contact
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-10 text-[#6B7280]">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#E5E7EB] bg-white p-8 text-center text-xs text-[#9CA3AF]">
          No customer-development rows yet.
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <RowCard
              key={r.id}
              row={r}
              onSave={(patch) => update.mutateAsync({ id: r.id, ...patch })}
              onDelete={() => remove.mutate(r.id)}
              savePending={update.isPending}
              deletePending={remove.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface RowCardProps {
  row: KamCustomerDevRow
  onSave: (patch: {
    contact_name?: string
    last_day_spoke?: string | null
    last_day_spoke_set?: boolean
    opportunity_areas?: string
    action_plan?: string
  }) => Promise<unknown>
  onDelete: () => void
  savePending: boolean
  deletePending: boolean
}

function RowCard({
  row,
  onSave,
  onDelete,
  savePending,
  deletePending,
}: RowCardProps) {
  const [name, setName] = useState(row.contact_name)
  const [date, setDate] = useState(row.last_day_spoke ?? "")
  const [opp, setOpp] = useState(row.opportunity_areas)
  const [plan, setPlan] = useState(row.action_plan)

  const dirty =
    name !== row.contact_name ||
    (row.last_day_spoke ?? "") !== date ||
    opp !== row.opportunity_areas ||
    plan !== row.action_plan

  const doSave = async () => {
    await onSave({
      contact_name: name.trim() || row.contact_name,
      last_day_spoke: date || null,
      last_day_spoke_set: true,
      opportunity_areas: opp,
      action_plan: plan,
    })
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Contact name
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Last day we spoke
          </label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
          />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={doSave}
            disabled={!dirty || savePending}
            className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-3 py-1.5 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-50"
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
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Opportunity areas
          </label>
          <textarea
            rows={4}
            value={opp}
            onChange={(e) => setOpp(e.target.value)}
            className="rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-2 text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Action plan
          </label>
          <textarea
            rows={4}
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            className="rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-2 text-xs"
          />
        </div>
      </div>
    </div>
  )
}
