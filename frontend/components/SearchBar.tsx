"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { useSearchReports, useTrending, type Report } from "@/lib/api"
import { Search, X } from "lucide-react"

const CATEGORY_COLORS: Record<string, string> = {
  Executive: "bg-[#1B3A5C]",
  Finance: "bg-[#1D4ED8]",
  Operations: "bg-[#D97706]",
  Sales: "bg-[#7C3AED]",
  HR: "bg-[#0D9488]",
  IT: "bg-[#6366F1]",
}

export function SearchBar() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const router = useRouter()

  const { data: searchResults } = useSearchReports(query)
  const { data: trendingResults } = useTrending()

  // Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
      if (e.key === "Escape" && open) {
        setOpen(false)
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [open])

  // Focus input when opening
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    } else {
      setQuery("")
    }
  }, [open])

  // Close when clicking outside
  useEffect(() => {
    if (!open) return
    function onClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", onClickOutside)
    return () => document.removeEventListener("mousedown", onClickOutside)
  }, [open])

  const handleSelect = useCallback(
    (reportId: string) => {
      setOpen(false)
      setQuery("")
      router.push(`/reports/${reportId}`)
    },
    [router],
  )

  const searchHits = searchResults?.data ?? []
  const trending = trendingResults?.data ?? []
  const results = query.length > 0 ? searchHits : trending
  const heading = query.length > 0 ? "Results" : "Trending this week"

  return (
    <>
      {/* Search trigger button */}
      <button
        onClick={() => setOpen(true)}
        className="mx-auto flex h-[52px] w-full max-w-[640px] items-center gap-3 rounded-2xl border border-[#E5E7EB] bg-white px-5 text-[#6B7280] shadow-sm transition-shadow hover:shadow-md"
      >
        <Search className="h-5 w-5" />
        <span className="flex-1 text-left text-[15px]">
          Search reports, KPIs, departments...
        </span>
        <kbd className="hidden rounded-md border border-[#E5E7EB] px-2 py-0.5 text-xs text-[#6B7280] sm:inline">
          ⌘K
        </kbd>
      </button>

      {/* Search overlay */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/10 pt-[20vh] backdrop-blur-xs">
          <div
            ref={panelRef}
            className="w-full max-w-lg animate-in fade-in-0 zoom-in-95 rounded-xl bg-white shadow-2xl ring-1 ring-[#E5E7EB]"
          >
            {/* Search input */}
            <div className="flex items-center gap-3 border-b border-[#E5E7EB] px-4 py-3">
              <Search className="h-4 w-4 shrink-0 text-[#9CA3AF]" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search reports, KPIs, departments..."
                className="w-full bg-transparent text-sm outline-none placeholder:text-[#9CA3AF]"
              />
              {query && (
                <button
                  onClick={() => setQuery("")}
                  className="shrink-0 text-[#9CA3AF] hover:text-[#6B7280]"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* Results */}
            <div className="max-h-72 overflow-y-auto p-1">
              {results.length > 0 ? (
                <div>
                  <p className="px-3 py-1.5 text-xs font-medium text-[#9CA3AF]">
                    {heading}
                  </p>
                  {results.map((report) => (
                    <ReportRow
                      key={report.id}
                      report={report}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              ) : query.length > 0 ? (
                <p className="py-6 text-center text-sm text-[#6B7280]">
                  No reports found.
                </p>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function ReportRow({
  report,
  onSelect,
}: {
  report: Report
  onSelect: (id: string) => void
}) {
  return (
    <button
      onClick={() => onSelect(report.id)}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-[#F3F4F6]"
    >
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white ${
          CATEGORY_COLORS[report.category ?? ""] ?? "bg-gray-500"
        }`}
      >
        {report.title.slice(0, 2).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[#111827]">
          {report.title}
        </p>
        {report.description && (
          <p className="truncate text-xs text-[#6B7280]">
            {report.description}
          </p>
        )}
      </div>
      {report.category && (
        <span className="shrink-0 rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] font-medium text-[#6B7280]">
          {report.category}
        </span>
      )}
    </button>
  )
}
