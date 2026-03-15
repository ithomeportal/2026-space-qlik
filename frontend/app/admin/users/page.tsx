"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Search, RefreshCw } from "lucide-react"

interface User {
  id: string
  email: string
  name: string | null
  department: string | null
  job_title: string | null
  is_active: boolean
  roles: string[]
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [search, setSearch] = useState("")
  const [syncing, setSyncing] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)

  useEffect(() => {
    loadUsers()
  }, [])

  async function loadUsers(query?: string) {
    const url = query
      ? `/api/proxy/admin/users?search=${encodeURIComponent(query)}`
      : "/api/proxy/admin/users"
    const res = await fetch(url)
    const json = await res.json()
    if (json.success) setUsers(json.data)
  }

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    loadUsers(search)
  }

  async function handleSync() {
    setSyncing(true)
    try {
      const res = await fetch("/api/proxy/admin/sync-users", { method: "POST" })
      const json = await res.json()
      if (json.success) {
        const d = json.data
        setLastSync(
          `Synced ${d.synced} users (${d.new_users} new, ${d.deactivated} deactivated)`
        )
        await loadUsers(search || undefined)
      }
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-[#1B3A5C]">User Management</h1>
        <div className="flex items-center gap-3">
          {lastSync && (
            <span className="text-sm text-[#6B7280]">{lastSync}</span>
          )}
          <Button
            onClick={handleSync}
            disabled={syncing}
            variant="outline"
            size="sm"
          >
            <RefreshCw
              className={`mr-2 h-4 w-4 ${syncing ? "animate-spin" : ""}`}
            />
            {syncing ? "Syncing..." : "Sync from People App"}
          </Button>
        </div>
      </div>

      <p className="text-sm text-[#6B7280]">
        Users are automatically synced from the People Management app daily at
        2:00 AM CST.
      </p>

      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#6B7280]" />
          <Input
            placeholder="Search by name or email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
        <Button type="submit" variant="outline">
          Search
        </Button>
      </form>

      <div className="rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-[#F9FAFB] text-left text-[#6B7280]">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Department</th>
              <th className="px-4 py-3">Role Name</th>
              <th className="px-4 py-3">Tag Roles</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-b last:border-0">
                <td className="px-4 py-3 font-medium">{user.name ?? "—"}</td>
                <td className="px-4 py-3 text-[#6B7280]">{user.email}</td>
                <td className="px-4 py-3">{user.department ?? "—"}</td>
                <td className="px-4 py-3">{user.job_title ?? "—"}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {(user.roles ?? []).map((role) => (
                      <Badge key={role} variant="secondary" className="text-xs">
                        {role}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge variant={user.is_active ? "default" : "secondary"}>
                    {user.is_active ? "Active" : "Inactive"}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
