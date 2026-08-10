"use client"

import { useEffect, useState } from "react"
import { Loader2, Save } from "lucide-react"
import { useBookerNote, useSaveBookerNote } from "@/lib/booker-scorecard-api"

/**
 * Free-text "Action Plan" box (Bruno Request 5). Per user — one row keyed on
 * user_id — so nobody edits anyone else's notes.
 *
 * Explicit Save rather than autosave, matching the other notes boxes in the
 * portal (KAM top-lanes / customer-dev): an autosaving textarea over a cold
 * Render backend loses keystrokes on the 30–60s cold start.
 */
export function ActionPlan() {
  const { data, isLoading, error } = useBookerNote()
  const save = useSaveBookerNote()

  const saved = data?.data?.notes ?? ""
  const updatedAt = data?.data?.updated_at ?? null
  const [draft, setDraft] = useState("")
  const [loaded, setLoaded] = useState(false)

  // Seed the textarea once, then leave it alone: re-syncing on every refetch
  // would wipe whatever the user is typing.
  //
  // ⚠ `loaded` must also flip on ERROR. It gates `dirty`, which gates the Save
  // button — so if the GET fails (cold start burning both retries, or the
  // notes table missing on a fresh deploy) and we only ever set it on success,
  // the user types a full action plan into a normal-looking textarea and Save
  // stays greyed out forever, with nothing on screen explaining why.
  useEffect(() => {
    if (!loaded && (data?.data || error)) {
      setDraft(data?.data?.notes ?? "")
      setLoaded(true)
    }
  }, [data, error, loaded])

  const dirty = loaded && draft !== saved

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-semibold text-[#1B3A5C]">Action Plan</div>
        <div className="text-[10px] text-[#9CA3AF]">
          Private to you · action items, follow-ups and notes
        </div>
      </div>

      {isLoading && !loaded ? (
        <div className="flex h-24 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <>
          {error && (
            <div className="mb-2 rounded-md border border-[#FDE68A] bg-[#FFFBEB] px-2 py-1.5 text-[11px] text-[#92400E]">
              Could not load your saved notes (
              {error instanceof Error ? error.message : "unknown error"}). You
              can still type and save — saving will overwrite whatever is stored.
            </div>
          )}
          <textarea
            rows={6}
            value={draft}
            maxLength={5000}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="What needs to happen next? Follow-ups, coaching points, carrier issues…"
            className="w-full rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs leading-relaxed focus:border-[#1B3A5C] focus:outline-none"
          />
          <div className="mt-2 flex items-center gap-3">
            <button
              onClick={() => save.mutate(draft)}
              disabled={save.isPending || !dirty}
              className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-3 py-1.5 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-50"
            >
              {save.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save
            </button>
            {dirty ? (
              <span className="text-[10px] text-[#B45309]">Unsaved changes</span>
            ) : updatedAt ? (
              <span className="text-[10px] text-[#9CA3AF]">
                Saved {new Date(updatedAt).toLocaleString("en-US")}
              </span>
            ) : null}
            <span className="ml-auto text-[10px] text-[#9CA3AF]">
              {draft.length} / 5000
            </span>
          </div>
        </>
      )}
    </div>
  )
}
