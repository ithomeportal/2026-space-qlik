"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { useSearch, useTrending, type SearchResult, type Report } from "@/lib/api"
import { Search, X, ExternalLink } from "lucide-react"

const CATEGORY_COLORS: Record<string, string> = {
  Executive: "bg-[#1B3A5C]",
  Finance: "bg-[#1D4ED8]",
  Operations: "bg-[#D97706]",
  Sales: "bg-[#7C3AED]",
  HR: "bg-[#0D9488]",
  IT: "bg-[#6366F1]",
}

export function SearchBar() {
  const [query, setQuery] = useState("")
  const [focused, setFocused] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const router = useRouter()

  const { data: searchResults } = useSearch(query)
  const { data: trendingResults } = useTrending()

  // Cmd+K / Ctrl+K shortcut to focus
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        inputRef.current?.focus()
      }
      if (e.key === "Escape" && focused) {
        inputRef.current?.blur()
        setFocused(false)
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [focused])

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!focused) return
    function onClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setFocused(false)
      }
    }
    document.addEventListener("mousedown", onClickOutside)
    return () => document.removeEventListener("mousedown", onClickOutside)
  }, [focused])

  const handleSelectReport = useCallback(
    (reportId: string) => {
      setQuery("")
      setFocused(false)
      inputRef.current?.blur()
      router.push(`/reports/${reportId}`)
    },
    [router],
  )

  const handleSelectApp = useCallback((url: string) => {
    setQuery("")
    setFocused(false)
    inputRef.current?.blur()
    window.open(url, "_blank", "noopener,noreferrer")
  }, [])

  // Split search results
  const searchHits = searchResults?.data ?? []
  const searchReports = searchHits.filter((r) => r.result_type === "report")
  const searchApps = searchHits.filter((r) => r.result_type === "app")
  const trending = trendingResults?.data ?? []

  const showDropdown = focused
  const hasResults = query.length > 0
    ? searchReports.length > 0 || searchApps.length > 0
    : trending.length > 0

  return (
    <div ref={wrapperRef} className="relative mx-auto w-full max-w-[640px]">
      {/* Inline search input — type directly like Google */}
      <div
        className={`flex h-[52px] items-center gap-3 rounded-2xl border bg-white px-5 shadow-sm transition-all ${
          focused
            ? "border-[#2563EB] ring-2 ring-[#2563EB]/20 shadow-md"
            : "border-[#E5E7EB] hover:shadow-md"
        }`}
      >
        <Search className="h-5 w-5 shrink-0 text-[#9CA3AF]" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          placeholder="Search reports, apps, notes..."
          className="w-full bg-transparent text-[15px] text-[#111827] outline-none placeholder:text-[#9CA3AF]"
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            className="shrink-0 text-[#9CA3AF] hover:text-[#6B7280]"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        <kbd className="hidden shrink-0 rounded-md border border-[#E5E7EB] px-2 py-0.5 text-xs text-[#9CA3AF] sm:inline">
          ⌘K
        </kbd>
      </div>

      {/* Dropdown results — appears below the search bar */}
      {showDropdown && hasResults && (
        <div className="absolute left-0 right-0 top-[58px] z-50 rounded-xl bg-white shadow-2xl ring-1 ring-[#E5E7EB]">
          <div className="max-h-72 overflow-y-auto p-1">
            {/* Search mode: reports */}
            {query.length > 0 && searchReports.length > 0 && (
              <div>
                <p className="px-3 py-1.5 text-xs font-medium text-[#9CA3AF]">
                  Reports
                </p>
                {searchReports.map((r) => (
                  <ReportRow
                    key={r.id}
                    report={r}
                    onSelect={handleSelectReport}
                  />
                ))}
              </div>
            )}

            {/* Search mode: apps */}
            {query.length > 0 && searchApps.length > 0 && (
              <div>
                <p className="px-3 py-1.5 text-xs font-medium text-[#9CA3AF]">
                  Apps
                </p>
                {searchApps.map((r) => (
                  <AppRow
                    key={r.id}
                    app={r}
                    onSelect={handleSelectApp}
                  />
                ))}
              </div>
            )}

            {/* Idle: trending */}
            {query.length === 0 && trending.length > 0 && (
              <div>
                <p className="px-3 py-1.5 text-xs font-medium text-[#9CA3AF]">
                  Trending this week
                </p>
                {trending.map((report) => (
                  <ReportRow
                    key={report.id}
                    report={report}
                    onSelect={handleSelectReport}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* No results message */}
      {showDropdown && query.length > 0 && !hasResults && (
        <div className="absolute left-0 right-0 top-[58px] z-50 rounded-xl bg-white shadow-2xl ring-1 ring-[#E5E7EB]">
          <p className="py-6 text-center text-sm text-[#6B7280]">
            No results found.
          </p>
        </div>
      )}
    </div>
  )
}

function ReportRow({
  report,
  onSelect,
}: {
  report: SearchResult | Report
  onSelect: (id: string) => void
}) {
  const category = "category" in report ? report.category : null

  return (
    <button
      onClick={() => onSelect(report.id)}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-[#F3F4F6]"
    >
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white ${
          CATEGORY_COLORS[category ?? ""] ?? "bg-gray-500"
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
      {category && (
        <span className="shrink-0 rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] font-medium text-[#6B7280]">
          {category}
        </span>
      )}
    </button>
  )
}

function AppRow({
  app,
  onSelect,
}: {
  app: SearchResult
  onSelect: (url: string) => void
}) {
  return (
    <button
      onClick={() => onSelect(app.url ?? "")}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-[#F3F4F6]"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[#EFF6FF]">
        {app.icon_data ? (
          <img src={app.icon_data} alt={app.title} className="h-5 w-5 rounded" />
        ) : (
          <ExternalLink className="h-4 w-4 text-[#2563EB]" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[#111827]">
          {app.title}
        </p>
        {app.description && (
          <p className="truncate text-xs text-[#6B7280]">
            {app.description}
          </p>
        )}
      </div>
      <span className="shrink-0 rounded-full bg-[#EFF6FF] px-2 py-0.5 text-[10px] font-medium text-[#2563EB]">
        App
      </span>
    </button>
  )
}
