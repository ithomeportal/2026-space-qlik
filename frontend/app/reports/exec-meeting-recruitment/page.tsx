"use client"

import { Suspense, useCallback } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2 } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  useEmrAnnual,
  useEmrFilterOptions,
  useEmrFreshness,
  useEmrOpenRoles,
  useEmrPeopleFlow,
  useEmrSummary,
  type EmrFilters,
  type PeopleRange,
} from "@/lib/exec-meeting-recruitment-api"
import { KpiCards } from "./KpiCards"
import { AnnualMovement } from "./AnnualMovement"
import { PeopleFlow } from "./PeopleFlow"
import { OpenCapacity } from "./OpenCapacity"

const ALL = "__all__"

function ExecMeetingRecruitmentContent() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const updateUrl = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        next.delete(k)
        if (v !== null && v !== undefined && v !== "") next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname]
  )

  const department = searchParams.get("dept")
  const filters: EmrFilters = { department }

  const optionsQ = useEmrFilterOptions()
  const years = optionsQ.data?.data?.years ?? []
  const departments = optionsQ.data?.data?.departments ?? []

  const yearParam = Number(searchParams.get("year"))
  const year = years.includes(yearParam) ? yearParam : (years[0] ?? new Date().getFullYear())

  const rangeParam = (searchParams.get("range") ?? "12m") as PeopleRange
  const range: PeopleRange = ["6m", "12m", "all", "custom"].includes(rangeParam)
    ? rangeParam
    : "12m"
  const urlFrom = searchParams.get("from") ?? ""
  const urlTo = searchParams.get("to") ?? ""

  const summaryQ = useEmrSummary(filters)
  const annualQ = useEmrAnnual(filters, year)
  const peopleQ = useEmrPeopleFlow(filters, range, urlFrom, urlTo)
  const rolesQ = useEmrOpenRoles(filters)
  const freshQ = useEmrFreshness()

  const window = peopleQ.data?.data?.window
  const fresh = freshQ.data?.data

  return (
    <div className="min-h-[calc(100vh-64px)] bg-[#F9FAFB]">
      {/* Sticky filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center gap-4 px-6 py-3">
          <Link
            href="/"
            className="flex items-center gap-1 text-xs text-[#6B7280] hover:text-[#111827]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Reports
          </Link>

          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Exec Meeting – Recruitment
          </h1>

          <label className="flex items-center gap-2 text-xs">
            <span className="font-semibold uppercase tracking-wider text-[#9CA3AF]">
              Department
            </span>
            <select
              value={department ?? ALL}
              onChange={(e) =>
                updateUrl({ dept: e.target.value === ALL ? null : e.target.value })
              }
              disabled={optionsQ.isLoading}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            >
              <option value={ALL}>All departments</option>
              {departments.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>

          <div className="ml-auto flex items-center gap-3 text-[11px] text-[#6B7280]">
            {fresh?.tickets ? (
              <span
                className={
                  fresh.is_stale ? "rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[#92400E]" : ""
                }
                title={`Offboarding tickets ${fresh.tickets}${fresh.people ? ` · people records ${fresh.people}` : ""}`}
              >
                Data as of {fresh.tickets}
                {fresh.is_stale ? " · stale" : ""}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1400px] space-y-5 px-6 py-6">
        <KpiCards
          data={summaryQ.data?.data}
          loading={summaryQ.isLoading}
          scoped={Boolean(department)}
        />

        <AnnualMovement
          data={annualQ.data?.data}
          loading={annualQ.isLoading}
          years={years}
          year={year}
          onYear={(y) => updateUrl({ year: String(y) })}
        />

        <PeopleFlow
          data={peopleQ.data?.data}
          loading={peopleQ.isLoading}
          range={range}
          onRange={(r) => updateUrl({ range: r, from: null, to: null })}
          startDate={urlFrom || window?.from || ""}
          endDate={urlTo || window?.to || ""}
          onStartDate={(v) =>
            updateUrl({ range: "custom", from: v, to: urlTo || window?.to || "" })
          }
          onEndDate={(v) =>
            updateUrl({ range: "custom", to: v, from: urlFrom || window?.from || "" })
          }
        />

        <OpenCapacity data={rolesQ.data?.data} loading={rolesQ.isLoading} />
      </div>
    </div>
  )
}

export default function ExecMeetingRecruitmentPage() {
  return (
    <ReportGuard reportKey="exec-meeting-recruitment">
      {/* Required: useSearchParams() forces dynamic rendering and the build
          fails without a Suspense boundary. */}
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <ExecMeetingRecruitmentContent />
      </Suspense>
    </ReportGuard>
  )
}
