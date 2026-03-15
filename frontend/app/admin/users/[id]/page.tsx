"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { ArrowLeft, Check, X, Save } from "lucide-react"

interface User {
  id: string
  email: string
  name: string | null
  department: string | null
  job_title: string | null
  is_active: boolean
  roles: string[]
}

interface Report {
  id: string
  title: string
  tag_roles: string[]
  is_active: boolean
}

interface Role {
  id: string
  name: string
}

export default function UserDetailPage() {
  const params = useParams()
  const router = useRouter()
  const userId = params.id as string

  const [user, setUser] = useState<User | null>(null)
  const [reports, setReports] = useState<Report[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [userRoles, setUserRoles] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  async function loadData() {
    const [usersRes, reportsRes, rolesRes] = await Promise.all([
      fetch(`/api/proxy/admin/users?limit=200`),
      fetch("/api/proxy/admin/reports?limit=200"),
      fetch("/api/proxy/admin/roles"),
    ])

    const usersJson = await usersRes.json()
    const reportsJson = await reportsRes.json()
    const rolesJson = await rolesRes.json()

    if (usersJson.success) {
      const found = usersJson.data.find(
        (u: User) => u.id === userId
      )
      if (found) {
        setUser(found)
        setUserRoles(found.roles ?? [])
      }
    }
    if (reportsJson.success) setReports(reportsJson.data)
    if (rolesJson.success) setRoles(rolesJson.data)
  }

  function toggleRole(roleName: string) {
    setSaved(false)
    setUserRoles((prev) =>
      prev.includes(roleName)
        ? prev.filter((r) => r !== roleName)
        : [...prev, roleName]
    )
  }

  async function handleSave() {
    if (!user) return
    setSaving(true)

    const roleIds = roles
      .filter((r) => userRoles.includes(r.name))
      .map((r) => r.id)

    await fetch(`/api/proxy/admin/users/${user.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role_ids: roleIds }),
    })

    setSaving(false)
    setSaved(true)
  }

  function reportHasAccess(report: Report): boolean {
    if (!report.tag_roles || report.tag_roles.length === 0) return false
    return report.tag_roles.some((tr) => userRoles.includes(tr))
  }

  // Non-admin roles for display
  const displayRoles = roles.filter((r) => r.name !== "admin")
  const activeReports = reports.filter((r) => r.is_active)
  const accessCount = activeReports.filter(reportHasAccess).length

  if (!user) {
    return (
      <div className="py-16 text-center text-[#6B7280]">Loading...</div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/admin/users")}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back
        </Button>
      </div>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#1B3A5C]">
            {user.name ?? user.email}
          </h1>
          <p className="mt-1 text-sm text-[#6B7280]">
            {user.email} &middot; {user.department ?? "No department"} &middot;{" "}
            {user.job_title ?? "No title"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && (
            <span className="text-sm text-green-600">Saved</span>
          )}
          <Button
            onClick={handleSave}
            disabled={saving}
            className="bg-[#2563EB]"
          >
            <Save className="mr-2 h-4 w-4" />
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      </div>

      {/* TagRole pills */}
      <div className="rounded-lg border bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-[#374151]">
          Tag Roles assigned to this user
        </h2>
        <div className="flex flex-wrap gap-2">
          {displayRoles.map((role) => (
            <button
              key={role.id}
              onClick={() => toggleRole(role.name)}
              className={`rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
                userRoles.includes(role.name)
                  ? "border-[#2563EB] bg-[#2563EB] text-white"
                  : "border-[#D1D5DB] text-[#6B7280] hover:border-[#9CA3AF] hover:bg-[#F9FAFB]"
              }`}
            >
              {role.name}
            </button>
          ))}
        </div>
      </div>

      {/* Report Access Matrix */}
      <div className="rounded-lg border bg-white">
        <div className="border-b px-4 py-3">
          <h2 className="text-sm font-semibold text-[#374151]">
            Report Access Matrix — {accessCount} of {activeReports.length}{" "}
            reports accessible
          </h2>
          <p className="mt-0.5 text-xs text-[#9CA3AF]">
            Each row shows a report and which TagRoles grant access. Toggle
            TagRoles above to change access.
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-[#F9FAFB] text-left text-xs text-[#6B7280]">
                <th className="sticky left-0 z-10 bg-[#F9FAFB] px-4 py-2">
                  Access
                </th>
                <th className="sticky left-[60px] z-10 bg-[#F9FAFB] px-4 py-2">
                  Report
                </th>
                {displayRoles.map((role) => (
                  <th
                    key={role.id}
                    className="px-3 py-2 text-center"
                  >
                    <button
                      onClick={() => toggleRole(role.name)}
                      className={`rounded px-2 py-0.5 transition-colors ${
                        userRoles.includes(role.name)
                          ? "bg-[#2563EB] text-white"
                          : "hover:bg-[#E5E7EB]"
                      }`}
                    >
                      {role.name}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {activeReports.map((report) => {
                const hasAccess = reportHasAccess(report)
                return (
                  <tr
                    key={report.id}
                    className={`border-b last:border-0 ${
                      hasAccess ? "bg-[#F0FDF4]" : ""
                    }`}
                  >
                    <td className="sticky left-0 z-10 px-4 py-2">
                      <div
                        className={
                          hasAccess ? "bg-[#F0FDF4]" : "bg-white"
                        }
                      >
                        {hasAccess ? (
                          <Check className="h-4 w-4 text-green-600" />
                        ) : (
                          <X className="h-4 w-4 text-red-300" />
                        )}
                      </div>
                    </td>
                    <td
                      className={`sticky left-[60px] z-10 px-4 py-2 font-medium ${
                        hasAccess
                          ? "bg-[#F0FDF4] text-[#111827]"
                          : "bg-white text-[#9CA3AF]"
                      }`}
                    >
                      {report.title}
                    </td>
                    {displayRoles.map((role) => {
                      const reportHasRole = (
                        report.tag_roles ?? []
                      ).includes(role.name)
                      const userHasRole = userRoles.includes(role.name)
                      const isMatch = reportHasRole && userHasRole

                      return (
                        <td
                          key={role.id}
                          className="px-3 py-2 text-center"
                        >
                          {reportHasRole && (
                            <span
                              className={`inline-block h-5 w-5 rounded text-center text-xs leading-5 ${
                                isMatch
                                  ? "bg-green-500 text-white"
                                  : "bg-[#F3F4F6] text-[#9CA3AF]"
                              }`}
                            >
                              {isMatch ? "✓" : "·"}
                            </span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
