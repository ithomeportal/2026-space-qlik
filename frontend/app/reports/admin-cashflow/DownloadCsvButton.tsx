"use client"

import { Download } from "lucide-react"

interface Props {
  href: string
  label?: string
  title?: string
}

/**
 * Anchor-style download button. The proxy at `/api/proxy/[...path]` passes
 * non-JSON bodies through, and the backend responds with
 * `Content-Disposition: attachment` so the browser saves the file.
 *
 * Same-origin GET carries the NextAuth session cookie automatically,
 * so no fetch+blob dance is needed.
 */
export function DownloadCsvButton({ href, label = "CSV", title }: Props) {
  return (
    <a
      href={href}
      download
      title={title ?? "Download as CSV"}
      className="inline-flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-[11px] text-[#374151] hover:bg-[#F9FAFB] hover:text-[#1B3A5C]"
    >
      <Download className="h-3 w-3" />
      {label}
    </a>
  )
}
