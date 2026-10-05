"use client"

import { useEffect, useState } from "react"
import { Check, Loader2, Pencil, Trash2, X } from "lucide-react"

import {
  useDeleteExpense,
  usePatchAccount,
  type GLAccount,
  type GLPatchBody,
} from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

/**
 * The six GL categories, fixed. `summary.gl_categories` only lists categories
 * that have rows in the selected month, so a picker built from it could not
 * move a row into (or add a row to) an empty category. Keys mirror the
 * backend's category keys.
 */
export const GL_CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "payroll", label: "Payroll & Personnel" },
  { value: "facilities", label: "Facilities & Parking" },
  { value: "subscriptions", label: "Dues & Subscriptions" },
  { value: "travel", label: "Travel & Transportation" },
  { value: "it", label: "IT & Technology" },
  { value: "other", label: "Other Expenses" },
]

const INPUT_CLASS = "rounded-md border px-2 py-1 text-xs"

interface EditDraft {
  code: string
  description: string
  category: string
  amount: string
}

const seed = (r: GLAccount): EditDraft => ({
  code: r.code,
  description: r.description,
  category: r.category,
  amount: String(r.amount),
})

/** Only the fields that differ from the row — PATCH sends nothing else, so a
 *  description edit cannot also re-write an amount someone changed meanwhile. */
function changedFields(r: GLAccount, d: EditDraft, amount: number): Omit<GLPatchBody, "id"> {
  return {
    ...(d.code.trim() !== r.code ? { code: d.code.trim() } : {}),
    ...(d.description.trim() !== r.description ? { description: d.description.trim() } : {}),
    ...(d.category !== r.category ? { category: d.category } : {}),
    ...(Math.round(amount * 100) !== Math.round(r.amount * 100) ? { amount } : {}),
  }
}

/**
 * One GL row — Bruno PDF 2026-10-05: EVERY row (template or added) can be
 * edited and deleted, not only the `is_custom` ones. The pencil switches the
 * row into inline edit mode; outside it the quick Amount input still works.
 */
export function GlAccountRow({ row }: { row: GLAccount }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<EditDraft>(() => seed(row))
  const patch = usePatchAccount()
  const del = useDeleteExpense()

  const amountNum = Number(draft.amount)
  const valid =
    draft.description.trim().length > 0 &&
    draft.amount.trim().length > 0 &&
    Number.isFinite(amountNum) &&
    amountNum >= 0
  const rounded = Math.round(amountNum * 100) / 100

  const startEdit = () => {
    setDraft(seed(row))
    setEditing(true)
  }

  const saveEdit = () => {
    if (!valid) return
    const body = changedFields(row, draft, rounded)
    if (Object.keys(body).length === 0) {
      setEditing(false)
      return
    }
    patch.mutate({ id: row.id, ...body }, { onSuccess: () => setEditing(false) })
  }

  const confirmDelete = () => {
    if (window.confirm(`Delete GL ${row.code} — ${row.description}?`)) del.mutate(row.id)
  }

  const set = (k: keyof EditDraft) => (v: string) => setDraft((prev) => ({ ...prev, [k]: v }))

  return (
    <tr
      className="border-b last:border-0"
      style={{ borderColor: "#f1f5f9", opacity: row.included || editing ? 1 : 0.5 }}
    >
      <td />
      {editing ? (
        <>
          <td className="px-3 py-2">
            <input value={draft.code} onChange={(e) => set("code")(e.target.value)}
                   aria-label="GL Code" placeholder="GL Code"
                   className={`w-24 ${INPUT_CLASS} ${MONO}`} style={{ borderColor: DPC.border }} />
          </td>
          <td className="px-3 py-2">
            <div className="flex flex-wrap gap-1.5">
              <input value={draft.description} onChange={(e) => set("description")(e.target.value)}
                     aria-label="Description" placeholder="Description *"
                     className={`min-w-[160px] flex-1 ${INPUT_CLASS}`} style={{ borderColor: DPC.border }} />
              <CategorySelect value={draft.category} onChange={set("category")} />
            </div>
          </td>
          <td className="px-3 py-2 text-right">
            <input type="number" min={0} step="0.01" value={draft.amount}
                   onChange={(e) => set("amount")(e.target.value)} aria-label="Amount"
                   className={`w-32 text-right ${INPUT_CLASS} ${MONO}`}
                   style={{ borderColor: DPC.border, color: DPC.secondary }} />
          </td>
          <td className="px-3 py-2">
            <div className="flex items-center justify-end gap-1">
              <IconButton label="Save changes" onClick={saveEdit} disabled={!valid || patch.isPending}
                          hover="hover:bg-green-50 hover:text-green-700">
                {patch.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              </IconButton>
              <IconButton label="Cancel editing" onClick={() => setEditing(false)}
                          hover="hover:bg-slate-100 hover:text-slate-700">
                <X className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          </td>
        </>
      ) : (
        <>
          <td className={`px-3 py-2 text-[#475569] ${MONO}`}>{row.code}</td>
          <td className="px-3 py-2 text-[#334155]">
            {row.description}
            {row.is_custom ? (
              <span className="ml-2 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
                    style={{ background: `${DPC.gold}22`, color: DPC.gold }}>
                added
              </span>
            ) : null}
          </td>
          <td className="px-3 py-2 text-right">
            <AmountInput value={row.amount} label={`Amount for ${row.description}`}
                         onSave={(amount) => patch.mutate({ id: row.id, amount })} />
          </td>
          <td className="px-3 py-2">
            <div className="flex items-center justify-end gap-1">
              <IconButton label={`Edit ${row.description}`} onClick={startEdit}
                          hover="hover:bg-slate-100 hover:text-slate-700">
                <Pencil className="h-3.5 w-3.5" />
              </IconButton>
              <IconButton label={`Delete ${row.description}`} onClick={confirmDelete}
                          disabled={del.isPending} hover="hover:bg-red-50 hover:text-red-600">
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
              <Toggle checked={row.included} label={`Include ${row.description}`}
                      onChange={(v) => patch.mutate({ id: row.id, included: v })} />
            </div>
          </td>
        </>
      )}
    </tr>
  )
}

export function CategorySelect({
  value, onChange, className = INPUT_CLASS,
}: {
  value: string
  onChange: (v: string) => void
  className?: string
}) {
  // Native <select>: shadcn's Select sits on @base-ui, banned on React 18.
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Category"
            className={`bg-white ${className}`} style={{ borderColor: DPC.border }}>
      {GL_CATEGORY_OPTIONS.map((c) => (
        <option key={c.value} value={c.value}>
          {c.label}
        </option>
      ))}
    </select>
  )
}

function IconButton({
  label, onClick, disabled, hover, children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  hover: string
  children: React.ReactNode
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label}
            className={`rounded p-1 text-[#94a3b8] disabled:opacity-40 ${hover}`}>
      {children}
    </button>
  )
}

/**
 * The quick Amount (USD) cell — Bruno PDF 2026-08-24 R2.
 *
 * String state rather than a number so a half-typed value ("12.", "") survives
 * keystrokes, re-seeded from the server whenever the row's amount changes (a
 * month switch would otherwise leave the previous month's typed value sitting
 * over the new month's row — the bug `CalculatorCard` documents at its own
 * `useEffect`).
 *
 * Commits on blur and on Enter, and ONLY when the parsed value actually differs
 * from what the server holds — otherwise merely tabbing across the table would
 * fire a PATCH per row. Anything not a finite number ≥ 0 reverts to the server
 * value and is never sent: "only positive values are permitted" is enforced
 * here for the typist and again by `GLPatch.amount` (`ge=0`) for everyone else.
 */
function AmountInput({
  value, label, onSave,
}: {
  value: number
  label: string
  onSave: (amount: number) => void
}) {
  const [draft, setDraft] = useState(String(value))

  useEffect(() => {
    setDraft(String(value))
  }, [value])

  const commit = () => {
    const n = Number(draft)
    if (!Number.isFinite(n) || n < 0 || draft.trim() === "") {
      setDraft(String(value))
      return
    }
    const rounded = Math.round(n * 100) / 100
    if (rounded === value) {
      setDraft(String(value))
      return
    }
    onSave(rounded)
  }

  return (
    <input
      type="number"
      min={0}
      step="0.01"
      value={draft}
      aria-label={label}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur()
        if (e.key === "Escape") setDraft(String(value))
      }}
      className={`w-32 rounded-md border px-2 py-1 text-right ${MONO} focus:outline-none focus:ring-1`}
      style={{ borderColor: DPC.border, color: DPC.secondary }}
    />
  )
}

export function Toggle({
  checked, onChange, label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className="relative inline-flex h-5 w-9 items-center rounded-full transition"
      style={{ background: checked ? DPC.navy : "#cbd5e1" }}
    >
      <span
        className="inline-block h-3.5 w-3.5 rounded-full bg-white transition"
        style={{ transform: checked ? "translateX(20px)" : "translateX(3px)" }}
      />
    </button>
  )
}
