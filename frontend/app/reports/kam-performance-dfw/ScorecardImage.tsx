"use client"

import { useRef, useState } from "react"
import { Image as ImageIcon, ImagePlus, Loader2, X } from "lucide-react"
import {
  MAX_SCORECARD_IMAGE_BYTES,
  useScorecardImage,
  type KamScorecardRow,
} from "@/lib/kam-performance-dfw-api"

interface Props {
  row: KamScorecardRow
  onUpload: (dataUri: string, name: string) => void
  pending: boolean
}

/**
 * Per-row image cell: a "View" affordance that fetches the blob **only when
 * clicked**, plus an upload button.
 *
 * ⚠ No thumbnail, on purpose. There is no separate small rendition — the only
 * stored copy is the full ~2 MB base64 blob, so rendering a 32px preview would
 * download every row's full image on mount. That is exactly what moving the
 * blob out of the list response was meant to stop: 20 rows ≈ 44 MB of
 * concurrent requests through one 0.5-CPU Render dyno, strictly worse than the
 * single fat list response it replaced. Fetch on open, never on render.
 */
export function ScorecardImageCell({ row, onUpload, pending }: Props) {
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)

  // `null` until the user actually opens it — this is what keeps it lazy.
  const { data, isLoading } = useScorecardImage(open ? row.id : null)
  const src = data?.data?.image_data ?? null

  const pick = async (file: File | undefined) => {
    setErr(null)
    if (!file) return
    if (!/^image\/(png|jpe?g|webp|gif)$/.test(file.type)) {
      setErr("PNG, JPEG, WEBP or GIF only")
      return
    }
    if (file.size > MAX_SCORECARD_IMAGE_BYTES) {
      setErr(`Too large (${(file.size / 1024 / 1024).toFixed(1)} MB, max 1.5 MB)`)
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      onUpload(String(reader.result), file.name)
      if (fileRef.current) fileRef.current.value = ""
    }
    reader.onerror = () => setErr("Could not read the file")
    reader.readAsDataURL(file)
  }

  return (
    <div className="flex items-center gap-1.5">
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        onChange={(e) => pick(e.target.files?.[0])}
        className="hidden"
      />

      {row.has_image ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title={row.image_name ?? "View image"}
          className="inline-flex max-w-[140px] items-center gap-1 rounded border border-[#E5E7EB] px-1.5 py-0.5 text-[11px] text-[#1B3A5C] hover:bg-[#F3F4F6]"
        >
          <ImageIcon className="h-3 w-3 shrink-0" />
          <span className="truncate">{row.image_name ?? "View"}</span>
        </button>
      ) : (
        <span className="text-[#9CA3AF]">—</span>
      )}

      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        disabled={pending}
        title={row.has_image ? "Replace image" : "Upload image"}
        className="rounded p-1 text-[#9CA3AF] hover:bg-[#F3F4F6] hover:text-[#1B3A5C] disabled:opacity-30"
      >
        {pending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <ImagePlus className="h-3.5 w-3.5" />
        )}
      </button>

      {err && <span className="text-[10px] text-[#991B1B]">{err}</span>}

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
          onClick={() => setOpen(false)}
        >
          <div
            className="relative max-h-full max-w-3xl overflow-auto rounded-lg bg-white p-3"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute right-2 top-2 rounded p-1 text-[#6B7280] hover:bg-[#F3F4F6]"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
            {isLoading ? (
              <div className="flex h-40 w-64 items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
              </div>
            ) : src ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={src}
                  alt={row.image_name ?? "Scorecard"}
                  className="max-h-[75vh] w-auto"
                />
                <div className="mt-2 text-xs text-[#6B7280]">
                  {row.image_name ?? ""}
                </div>
              </>
            ) : (
              <div className="flex h-40 w-64 items-center justify-center text-xs text-[#991B1B]">
                Could not load the image.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
