"use client"

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { useSearchReports, useTrending, type Report } from "@/lib/api"
import { Search } from "lucide-react"

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
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [])

  const handleSelect = useCallback(
    (reportId: string) => {
      setOpen(false)
      setQuery("")
      router.push(`/reports/${reportId}`)
    },
    [router],
  )

  function renderReport(report: Report) {
    return (
      <CommandItem
        key={report.id}
        value={report.title}
        onSelect={() => handleSelect(report.id)}
        className="flex items-center gap-3 py-3"
      >
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white ${
            CATEGORY_COLORS[report.category ?? ""] ?? "bg-gray-500"
          }`}
        >
          {report.title.slice(0, 2).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{report.title}</p>
          {report.description && (
            <p className="truncate text-xs text-[#6B7280]">{report.description}</p>
          )}
        </div>
        {report.category && (
          <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
            {report.category}
          </span>
        )}
      </CommandItem>
    )
  }

  const searchHits = searchResults?.data ?? []
  const trending = trendingResults?.data ?? []

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

      {/* Command dialog */}
      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput
          placeholder="Search reports, KPIs, departments..."
          value={query}
          onValueChange={setQuery}
        />
        <CommandList>
          <CommandEmpty>No reports found.</CommandEmpty>

          {query.length > 0 && searchHits.length > 0 && (
            <CommandGroup heading="Results">
              {searchHits.map(renderReport)}
            </CommandGroup>
          )}

          {query.length === 0 && trending.length > 0 && (
            <CommandGroup heading="Trending this week">
              {trending.map(renderReport)}
            </CommandGroup>
          )}
        </CommandList>
      </CommandDialog>
    </>
  )
}
