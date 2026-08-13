"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, Info, Plus, Trash2, X } from "lucide-react"

import {
  formatCurrency,
  useAddExpense,
  useDeleteExpense,
  usePatchAccount,
  useToggleCategory,
  type GLCategory,
  type Summary,
} from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

/**
 * "GL Account Deductions" — PDF Calculator Request 5.
 *
 * Grouped by category, expand/collapse per group, an Include toggle at both the
 * category and the row level, and an Add Expense form.
 *
 * ⚠ Excluding a row raises the net payment by exactly that row's amount and
 * touches nothing else — profit, margin and the tariff are functions of revenue
 * and profit only. That invariant is asserted server-side
 * (`test_excluding_a_gl_row_raises_net_payment_by_exactly_that_amount`); this
 * component just posts the toggle and re-reads the recomputed summary, so the
 * two can never drift.
 */
export function GlDeductionsTable({ summary }: { summary: Summary }) {
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(summary.gl_categories.map((c) => c.category)),
  )
  const [showAdd, setShowAdd] = useState(false)

  const patch = usePatchAccount()
  const del = useDeleteExpense()
  const toggleCat = useToggleCategory(summary.year, summary.month)

  const toggleExpanded = (cat: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })

  return (
    <section className="rounded-xl border bg-white" style={{ borderColor: DPC.border }}>
      <header
        className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3"
        style={{ borderColor: DPC.border }}
      >
        <div>
          <h3 className="text-base font-bold" style={{ color: DPC.navy }}>
            GL Account Deductions
          </h3>
          <p className="text-[11px] text-[#94a3b8]">
            Toggle accounts to include or exclude from the calculation
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowAdd((v) => !v)}
          className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold text-white"
          style={{ background: DPC.navy }}
        >
          {showAdd ? <X className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
          {showAdd ? "Cancel" : "Add Expense"}
        </button>
      </header>

      {showAdd ? (
        <AddExpenseForm
          summary={summary}
          onDone={() => setShowAdd(false)}
        />
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-xs">
          <thead>
            <tr
              className="border-b text-[10px] uppercase tracking-wide text-[#64748b]"
              style={{ borderColor: DPC.border }}
            >
              <th className="w-8 px-3 py-2" />
              <th className="px-3 py-2 text-left font-semibold">GL Code</th>
              <th className="px-3 py-2 text-left font-semibold">Description</th>
              <th className="px-3 py-2 text-right font-semibold">Amount (USD)</th>
              <th className="w-20 px-3 py-2 text-right font-semibold">Include</th>
            </tr>
          </thead>
          <tbody>
            {summary.gl_categories.map((cat) => {
              const rows = summary.gl_accounts.filter((a) => a.category === cat.category)
              const open = expanded.has(cat.category)
              return (
                <CategoryGroup
                  key={cat.category}
                  cat={cat}
                  rows={rows}
                  open={open}
                  onToggleExpanded={() => toggleExpanded(cat.category)}
                  onToggleAll={(included) =>
                    toggleCat.mutate({ category: cat.category, included })
                  }
                  onToggleRow={(id, included) => patch.mutate({ id, included })}
                  onDelete={(id) => del.mutate(id)}
                />
              )
            })}
          </tbody>
          <tfoot>
            {/* colSpan derived from the header above (5 columns, 4 before the
                total) — a hardcoded value silently shifts money one column
                left when a column is added (§61). */}
            <tr className="border-t" style={{ borderColor: DPC.border, background: "#f8fafc" }}>
              <td className="px-3 py-3 font-semibold" colSpan={3} style={{ color: DPC.navy }}>
                Total Deductions
              </td>
              <td
                className={`px-3 py-3 text-right text-base font-bold ${MONO}`}
                style={{ color: DPC.navy }}
              >
                {formatCurrency(summary.gl_deductions)}
              </td>
              <td className="px-3 py-3 text-right text-[10px] text-[#94a3b8]">
                {summary.gl_included_count}/{summary.gl_row_count}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  )
}

function CategoryGroup({
  cat, rows, open, onToggleExpanded, onToggleAll, onToggleRow, onDelete,
}: {
  cat: GLCategory
  rows: Summary["gl_accounts"]
  open: boolean
  onToggleExpanded: () => void
  onToggleAll: (included: boolean) => void
  onToggleRow: (id: string, included: boolean) => void
  onDelete: (id: string) => void
}) {
  return (
    <>
      <tr className="border-b" style={{ borderColor: DPC.border }}>
        <td className="px-3 py-2.5">
          <button type="button" onClick={onToggleExpanded} aria-label="Expand category">
            {open ? (
              <ChevronDown className="h-4 w-4 text-[#94a3b8]" />
            ) : (
              <ChevronRight className="h-4 w-4 text-[#94a3b8]" />
            )}
          </button>
        </td>
        <td className="px-3 py-2.5" colSpan={2}>
          <button
            type="button"
            onClick={onToggleExpanded}
            className="flex items-center gap-2 text-sm font-semibold"
            style={{ color: DPC.navy }}
          >
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: cat.color }}
              aria-hidden
            />
            {cat.label}
            <span className="rounded-full bg-[#f1f5f9] px-1.5 py-0.5 text-[10px] font-normal text-[#64748b]">
              {cat.row_count}
            </span>
          </button>
        </td>
        <td className={`px-3 py-2.5 text-right font-semibold ${MONO}`} style={{ color: DPC.navy }}>
          {formatCurrency(cat.amount)}
        </td>
        <td className="px-3 py-2.5 text-right">
          <Toggle
            checked={cat.all_included}
            onChange={(v) => onToggleAll(v)}
            label={`Include all ${cat.label}`}
          />
        </td>
      </tr>

      {open
        ? rows.map((r) => (
            <tr
              key={r.id}
              className="border-b last:border-0"
              style={{ borderColor: "#f1f5f9", opacity: r.included ? 1 : 0.5 }}
            >
              <td />
              <td className={`px-3 py-2 text-[#475569] ${MONO}`}>{r.code}</td>
              <td className="px-3 py-2 text-[#334155]">
                {r.description}
                {r.is_custom ? (
                  <span
                    className="ml-2 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
                    style={{ background: `${DPC.gold}22`, color: DPC.gold }}
                  >
                    added
                  </span>
                ) : null}
              </td>
              <td className={`px-3 py-2 text-right ${MONO}`} style={{ color: DPC.secondary }}>
                {formatCurrency(r.amount)}
              </td>
              <td className="px-3 py-2">
                <div className="flex items-center justify-end gap-1.5">
                  {r.is_custom ? (
                    <button
                      type="button"
                      onClick={() => onDelete(r.id)}
                      aria-label="Delete added expense"
                      className="rounded p-1 text-[#94a3b8] hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                  <Toggle
                    checked={r.included}
                    onChange={(v) => onToggleRow(r.id, v)}
                    label={`Include ${r.description}`}
                  />
                </div>
              </td>
            </tr>
          ))
        : null}
    </>
  )
}

function Toggle({
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

function AddExpenseForm({ summary, onDone }: { summary: Summary; onDone: () => void }) {
  const [code, setCode] = useState("")
  const [category, setCategory] = useState(summary.gl_categories[0]?.category ?? "other")
  const [description, setDescription] = useState("")
  const [amount, setAmount] = useState("")
  const add = useAddExpense(summary.year, summary.month)

  const amountNum = Number(amount)
  const valid =
    description.trim().length > 0 &&
    amount.trim().length > 0 &&
    Number.isFinite(amountNum) &&
    amountNum >= 0 &&
    category.length > 0

  return (
    <form
      className="border-b px-4 py-3"
      style={{ borderColor: DPC.border, background: "#f8fafc" }}
      onSubmit={(e) => {
        e.preventDefault()
        if (!valid) return
        add.mutate(
          { code, category, description: description.trim(), amount: amountNum },
          {
            onSuccess: () => {
              setCode("")
              setDescription("")
              setAmount("")
              onDone()
            },
          },
        )
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="GL Code (optional)"
          aria-label="GL Code"
          className="rounded-md border px-2.5 py-1.5 text-sm"
          style={{ borderColor: DPC.border }}
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Category"
          className="rounded-md border bg-white px-2.5 py-1.5 text-sm"
          style={{ borderColor: DPC.border }}
        >
          {summary.gl_categories.map((c) => (
            <option key={c.category} value={c.category}>
              {c.label}
            </option>
          ))}
        </select>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description *"
          aria-label="Description"
          className="rounded-md border px-2.5 py-1.5 text-sm"
          style={{ borderColor: DPC.border }}
        />
        <input
          type="number"
          min={0}
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="Amount (USD) *"
          aria-label="Amount"
          className={`rounded-md border px-2.5 py-1.5 text-sm ${MONO}`}
          style={{ borderColor: DPC.border }}
        />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="submit"
          disabled={!valid || add.isPending}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
          style={{ background: DPC.gold }}
        >
          Add Expense
        </button>
        <span className="flex items-center gap-1 text-[10px] text-[#94a3b8]">
          <Info className="h-3 w-3" />
          Added rows can be deleted; template rows can only be excluded.
        </span>
      </div>
    </form>
  )
}
