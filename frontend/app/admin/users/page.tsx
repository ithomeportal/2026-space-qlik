"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Search } from "lucide-react"

interface User {
  id: string
  email: string
  name: string | null
  department: string | null
  company: string | null
  is_active: boolean
  roles: string[]
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [search, setSearch] = useState("")

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

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-[#1B3A5C]">User Management</h1>

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
              <th className="px-4 py-3">Company</th>
              <th className="px-4 py-3">Roles</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-b last:border-0">
                <td className="px-4 py-3 font-medium">{user.name ?? "—"}</td>
                <td className="px-4 py-3 text-[#6B7280]">{user.email}</td>
                <td className="px-4 py-3">{user.department ?? "—"}</td>
                <td className="px-4 py-3">{user.company ?? "—"}</td>
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
