"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, DoorOpen, Loader2, ChevronLeft, ChevronRight } from "lucide-react"
import {
  useScopedAccessFilters,
  useScopedAccessKpis,
  useScopedAccessRows,
  useScopedAccessTrend30d,
  useScopedAccessByJobTitle,
  fmtCount,
  fmtPct,
  fmtEventTime,
  fmtCheckMinutes,
  fmtDate,
  fmtExpectedTime,
  checkColorClass,
  type ScopedAccessFilters,
  type ScopedAccessSlug,
} from "@/lib/scoped-access-api"
import { AccessErrorBanner } from "./ErrorBanner"
import { AccessTrendChart } from "./TrendChart"
import { AccessJobTitleBarChart } from "./JobTitleBarChart"

/**
 * Shared body for every scope-locked "Access Log Doors" report (OPS / Pricing /
 * Carrier Procurement — Bruno PDF 2026-08-12).
 *
 * There is no Department dropdown anywhere: the scope is a hard-coded SQL gate
 * in `scoped_access_doors.py`, so it can't be widened from the client. Reports
 * gated by job title rather than department pass `showJobTitleFilter={false}`
 * so the Job Title dropdown disappears too — the `/by-job-title` chart still
 * renders the gated titles, since a chart is not a filter.
 *
 * Each page wraps this in its own `<ReportGuard reportKey={slug}>`.
 */

interface Props {
  slug: ScopedAccessSlug
  /** Page heading, e.g. "OPS - Access Log Doors". */
  title: string
  /** Pill next to the heading + chart captions, e.g. "Operations". */
  scopeLabel: string
  /** False for job-title-gated reports (Carrier Procurement). */
  showJobTitleFilter?: boolean
}

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export function ScopedAccessDoorsReport({
  slug,
  title,
  scopeLabel,
  showJobTitleFilter = true,
}: Props) {
  const today = todayIso()
  const [startDate, setStartDate] = useState<string>(today)
  const [endDate, setEndDate] = useState<string>(today)
  const [name, setName] = useState<string>("")
  const [jobTitle, setJobTitle] = useState<string>("")
  const [team, setTeam] = useState<string>("")
  const [sort, setSort] = useState<string>("event_time_desc")
  const [page, setPage] = useState<number>(1)
  const PAGE_LIMIT = 100

  const { data: filterRes, isLoading: loadingFilters } = useScopedAccessFilters(slug)
  const options = filterRes?.data

  // `jobTitle` can only ever be set when the dropdown is rendered, but guard
  // here too so hiding the filter can never leave a stale value scoping data.
  const activeJobTitle = showJobTitleFilter ? jobTitle || undefined : undefined

  const filters: ScopedAccessFilters = useMemo(
    () => ({
      startDate,
      endDate,
      name: name || undefined,
      jobTitle: activeJobTitle,
      team: team || undefined,
    }),
    [startDate, endDate, name, activeJobTitle, team],
  )

  const kpisQ = useScopedAccessKpis(slug, filters)
  const rowsQ = useScopedAccessRows(slug, { ...filters, sort, page, limit: PAGE_LIMIT })
  const trendQ = useScopedAccessTrend30d(slug, {
    name: filters.name,
    jobTitle: filters.jobTitle,
    team: filters.team,
  })
  // job title is deliberately omitted so the chart keeps more than one bar;
  // team is not — narrowing to one team is the whole point of that filter, and
  // a team spans several job titles.
  const jobTitleQ = useScopedAccessByJobTitle(slug, {
    startDate: filters.startDate,
    endDate: filters.endDate,
    name: filters.name,
    team: filters.team,
  })

  const kpi = kpisQ.data?.data
  const rows = rowsQ.data?.data ?? []
  const total = rowsQ.data?.meta?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_LIMIT))

  function clearFilters() {
    setStartDate(today)
    setEndDate(today)
    setName("")
    setJobTitle("")
    setTeam("")
    setPage(1)
  }

  const dirty =
    name !== "" ||
    (showJobTitleFilter && jobTitle !== "") ||
    team !== "" ||
    startDate !== today ||
    endDate !== today

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link
          href="/"
          className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <DoorOpen className="h-4 w-4 text-[#0F766E]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">{title}</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1E40AF]">
            {scopeLabel}
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {startDate === endDate ? startDate : `${startDate} → ${endDate}`}
          {name ? ` · ${name}` : ""}
          {activeJobTitle ? ` · ${activeJobTitle}` : ""}
          {team ? ` · ${team}` : ""}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value)
                setPage(1)
              }}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            <span className="text-xs text-[#9CA3AF]">→</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value)
                setPage(1)
              }}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
          </div>

          <SelectFilter
            label="Name"
            value={name}
            onChange={(v) => {
              setName(v)
              setPage(1)
            }}
            options={options?.names}
            placeholder={loadingFilters ? "Loading…" : "All"}
          />
          {showJobTitleFilter && (
            <SelectFilter
              label="Job Title"
              value={jobTitle}
              onChange={(v) => {
                setJobTitle(v)
                setPage(1)
              }}
              options={options?.job_titles}
              placeholder={loadingFilters ? "Loading…" : "All"}
            />
          )}
          <SelectFilter
            label="Team"
            value={team}
            onChange={(v) => {
              setTeam(v)
              setPage(1)
            }}
            options={options?.teams}
            placeholder={loadingFilters ? "Loading…" : "All"}
          />

          {dirty && (
            <button
              onClick={clearFilters}
              className="ml-auto rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-5">
        <AccessErrorBanner
          errors={[kpisQ.error, rowsQ.error, trendQ.error, jobTitleQ.error]}
        />

        {/* KPI cards */}
        <section className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <KpiCard label="Log In Employees" value={fmtCount(kpi?.log_in_employees)} color="#1B3A5C" />
          <KpiCard
            label="Not On Time Reference"
            value={fmtCount(kpi?.not_on_time_ref)}
            color="#6B7280"
          />
          <KpiCard label="On Time" value={fmtCount(kpi?.on_time)} color="#047857" />
          <KpiCard label="Out of Time" value={fmtCount(kpi?.out_of_time)} color="#DC2626" />
          <KpiCard label="% On Time" value={fmtPct(kpi?.pct_on_time)} color="#047857" />
          <KpiCard label="% Out of Time" value={fmtPct(kpi?.pct_out_of_time)} color="#DC2626" />
        </section>

        {/* Charts row */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-[#E5E7EB] bg-white p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#374151]">
              On Time – Out of Time Trend
            </h2>
            {trendQ.isLoading ? (
              <SkelBlock height={200} />
            ) : (
              <AccessTrendChart
                points={trendQ.data?.data ?? []}
                scopeLabel={scopeLabel}
              />
            )}
          </div>
          <div>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#374151]">
              On Time – Out of Time by Job Title
            </h2>
            {jobTitleQ.isLoading ? (
              <div className="rounded-lg border border-[#E5E7EB] bg-white p-3">
                <SkelBlock height={200} />
              </div>
            ) : (
              <AccessJobTitleBarChart
                rows={jobTitleQ.data?.data ?? []}
                scopeLabel={scopeLabel}
              />
            )}
          </div>
        </section>

        {/* Table */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white">
          <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-[#111827]">Access Log Doors</h2>
              <span className="text-xs text-[#6B7280]">
                {fmtCount(total)} row{total === 1 ? "" : "s"}
              </span>
              <span
                className="text-xs text-[#9CA3AF]"
                title="An overnight shift is grouped by the evening it began, so a night worker's morning exit badge is not counted as an arrival."
              >
                · all times CST (America/Chicago)
              </span>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-[#6B7280]">Sort</label>
              <select
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value)
                  setPage(1)
                }}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              >
                <option value="event_time_desc">Access time (newest)</option>
                <option value="event_time_asc">Access time (oldest)</option>
                <option value="check_desc">Check (most early)</option>
                <option value="check_asc">Check (most late)</option>
                <option value="name_asc">Name A→Z</option>
                <option value="job_title">Job Title</option>
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">Name</th>
                  <th className="px-3 py-2 text-left font-semibold">Shift Date</th>
                  <th className="px-3 py-2 text-left font-semibold">Access Log Door (CST)</th>
                  <th className="px-3 py-2 text-left font-semibold">Job Title</th>
                  <th className="px-3 py-2 text-left font-semibold">Team</th>
                  <th className="px-3 py-2 text-right font-semibold">Check</th>
                  <th className="px-3 py-2 text-left font-semibold">On Time Reference (CST)</th>
                </tr>
              </thead>
              <tbody>
                {rowsQ.isLoading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-3 py-6 text-center text-[#9CA3AF]">
                      <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-3 py-6 text-center text-[#9CA3AF]">
                      No access events in this window.
                    </td>
                  </tr>
                ) : (
                  rows.map((r, i) => (
                    <tr
                      key={`${r.full_name}-${r.event_time}-${i}`}
                      className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]"
                    >
                      <td className="px-3 py-2 font-medium text-[#111827]">{r.full_name}</td>
                      <td className="px-3 py-2 text-[#374151]">{fmtDate(r.event_date)}</td>
                      <td className="px-3 py-2 text-[#374151]">
                        {fmtDate(r.event_date)} {fmtEventTime(r.event_time)}
                      </td>
                      <td className="px-3 py-2 text-[#374151]">{r.job_title || "—"}</td>
                      <td className="px-3 py-2 text-[#374151]">{r.team || "—"}</td>
                      <td className={`px-3 py-2 text-right ${checkColorClass(r.check_minutes)}`}>
                        {fmtCheckMinutes(r.check_minutes)}
                      </td>
                      <td className="px-3 py-2 text-[#374151]">
                        {fmtExpectedTime(r.on_time_reference)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-[#E5E7EB] px-4 py-2 text-xs text-[#6B7280]">
              <div>
                Page {page} of {totalPages}
              </div>
              <div className="flex items-center gap-1">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="rounded-md border border-[#E5E7EB] bg-white p-1 hover:bg-[#F3F4F6] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-3 w-3" />
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="rounded-md border border-[#E5E7EB] bg-white p-1 hover:bg-[#F3F4F6] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronRight className="h-3 w-3" />
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Small primitives
// ---------------------------------------------------------------------------

function KpiCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold leading-none" style={{ color }}>
        {value}
      </div>
    </div>
  )
}

function SelectFilter({
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options?: string[]
  placeholder: string
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[200px] rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
      >
        <option value="">{placeholder}</option>
        {(options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  )
}

function SkelBlock({ height }: { height: number }) {
  return (
    <div
      className="animate-pulse rounded bg-[#F3F4F6]"
      style={{ height: `${height}px` }}
    />
  )
}
