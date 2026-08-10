"use client"

import { useRef, useState } from "react"
import { Loader2, Plus, Trash2, X } from "lucide-react"
import {
  MAX_SCORECARD_IMAGE_BYTES,
  useCreateScorecard,
  useDeleteScorecard,
  useKamScorecards,
  useUpdateScorecard,
} from "@/lib/kam-performance-dfw-api"
import { fmtDate } from "./format"
import { ScorecardImageCell } from "./ScorecardImage"

const FREQUENCIES = ["Weekly", "Bi-Weekly", "Monthly", "Quarterly", "Yearly", "Ad-hoc"]

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

const fmtPercentage = (v: number | null) =>
  v === null || v === undefined ? "—" : `${v.toFixed(2).replace(/\.00$/, "")}%`

/**
 * Read a picked file as a base64 data URI.
 *
 * JSON transport, not multipart: the Next.js proxy reads the request body with
 * `req.text()` and forces `Content-Type: application/json`, so a multipart body
 * arrives corrupted. Base64-in-TEXT is the same pattern the app favicons use
 * and needs no CSP change (`img-src 'self' data: blob:`).
 */
function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error("Could not read the image file."))
    reader.readAsDataURL(file)
  })
}

function validateImage(file: File): string | null {
  if (!/^image\/(png|jpe?g|webp|gif)$/.test(file.type)) {
    return "Image must be a PNG, JPEG, WEBP or GIF."
  }
  if (file.size > MAX_SCORECARD_IMAGE_BYTES) {
    return `Image is too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max 1.5 MB.`
  }
  return null
}

export function Tab1Scorecards() {
  const { data, isLoading } = useKamScorecards()
  const create = useCreateScorecard()
  const update = useUpdateScorecard()
  const remove = useDeleteScorecard()

  const [customer, setCustomer] = useState("")
  const [scorecardDate, setScorecardDate] = useState(todayIso())
  const [frequency, setFrequency] = useState(FREQUENCIES[0])
  const [percentage, setPercentage] = useState("")
  const [image, setImage] = useState<{ data: string; name: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)

  const rows = data?.data ?? []

  const onPickFile = async (file: File | undefined) => {
    setErr(null)
    if (!file) return
    const problem = validateImage(file)
    if (problem) {
      setErr(problem)
      if (fileRef.current) fileRef.current.value = ""
      return
    }
    try {
      setImage({ data: await readAsDataUrl(file), name: file.name })
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read the image.")
    }
  }

  const onAdd = async () => {
    setErr(null)
    if (!customer.trim()) {
      setErr("Customer is required")
      return
    }
    // Empty means "not recorded", which is a real state — don't coerce it to 0.
    const pct = percentage.trim() === "" ? null : Number(percentage)
    if (pct !== null && (Number.isNaN(pct) || pct < -9999 || pct > 9999)) {
      setErr("Percentage must be a number between -9999 and 9999")
      return
    }
    try {
      await create.mutateAsync({
        customer: customer.trim(),
        scorecard_date: scorecardDate,
        scorecard_frequency: frequency,
        percentage: pct,
        image_data: image?.data ?? null,
        image_name: image?.name ?? null,
      })
      setCustomer("")
      setScorecardDate(todayIso())
      setFrequency(FREQUENCIES[0])
      setPercentage("")
      setImage(null)
      if (fileRef.current) fileRef.current.value = ""
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
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              Percentage
            </label>
            <input
              type="number"
              step="0.01"
              value={percentage}
              onChange={(e) => setPercentage(e.target.value)}
              placeholder="—"
              className="w-24 rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-right text-xs"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              Image
            </label>
            <div className="flex items-center gap-1.5">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={(e) => onPickFile(e.target.files?.[0])}
                className="w-56 text-[11px] file:mr-2 file:rounded file:border-0 file:bg-[#F3F4F6] file:px-2 file:py-1 file:text-[11px]"
              />
              {image && (
                <button
                  type="button"
                  onClick={() => {
                    setImage(null)
                    if (fileRef.current) fileRef.current.value = ""
                  }}
                  title="Remove image"
                  className="rounded p-1 text-[#9CA3AF] hover:bg-[#FEE2E2] hover:text-[#991B1B]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
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
        {image && (
          <div className="mt-3 flex items-center gap-2 text-[11px] text-[#6B7280]">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={image.data}
              alt="Selected scorecard"
              className="h-14 w-14 rounded border border-[#E5E7EB] object-cover"
            />
            <span className="truncate">{image.name}</span>
          </div>
        )}
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
                <th className="px-2 py-1.5 text-right">Percentage</th>
                <th className="px-2 py-1.5 text-left">Image</th>
                <th className="px-2 py-1.5 text-left">Uploaded at</th>
                <th className="px-2 py-1.5 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-[#9CA3AF]">
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
                    <td className="px-2 py-1.5 text-right">
                      <PercentageCell
                        id={r.id}
                        value={r.percentage}
                        onSave={(pct) =>
                          update.mutate({
                            id: r.id,
                            percentage: pct,
                            percentage_set: true,
                          })
                        }
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <ScorecardImageCell
                        row={r}
                        onUpload={(dataUri, name) =>
                          update.mutate({
                            id: r.id,
                            image_data: dataUri,
                            image_name: name,
                          })
                        }
                        // Scope the spinner to the row being saved — a bare
                        // `update.isPending` greys out every row's button.
                        pending={
                          update.isPending && update.variables?.id === r.id
                        }
                      />
                    </td>
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

/** Click-to-edit numeric cell, so Percentage can be set on existing rows. */
function PercentageCell({
  id,
  value,
  onSave,
}: {
  id: string
  value: number | null
  onSave: (pct: number | null) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [bad, setBad] = useState(false)

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setDraft(value === null ? "" : String(value))
          setEditing(true)
        }}
        className="rounded px-1 hover:bg-[#F3F4F6]"
        title="Click to edit"
      >
        {fmtPercentage(value)}
      </button>
    )
  }

  const commit = () => {
    const pct = draft.trim() === "" ? null : Number(draft)
    // Stay in edit mode and say so. Silently closing and snapping the old value
    // back reads as "my click didn't register" — the add-form path explains
    // itself, and these two must not disagree.
    if (pct !== null && (Number.isNaN(pct) || pct < -9999 || pct > 9999)) {
      setBad(true)
      return
    }
    setBad(false)
    if (pct !== value) onSave(pct)
    setEditing(false)
  }

  return (
    <span className="inline-flex flex-col items-end">
      <input
        autoFocus
        type="number"
        step="0.01"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          setBad(false)
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit()
          if (e.key === "Escape") {
            setBad(false)
            setEditing(false)
          }
        }}
        aria-label={`Percentage for scorecard ${id}`}
        aria-invalid={bad}
        className={`w-20 rounded border px-1 py-0.5 text-right text-xs ${
          bad ? "border-[#991B1B]" : "border-[#1B3A5C]"
        }`}
      />
      {bad && (
        <span className="text-[9px] text-[#991B1B]">-9999 to 9999</span>
      )}
    </span>
  )
}
