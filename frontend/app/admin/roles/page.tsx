"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Plus, Trash2 } from "lucide-react"

interface Role {
  id: string
  name: string
  description: string | null
  user_count: number
}

export default function AdminRolesPage() {
  const [roles, setRoles] = useState<Role[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: "", description: "" })

  useEffect(() => {
    loadRoles()
  }, [])

  async function loadRoles() {
    const res = await fetch("/api/proxy/admin/roles")
    const json = await res.json()
    if (json.success) setRoles(json.data)
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    await fetch("/api/proxy/admin/roles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    })
    setShowCreate(false)
    setForm({ name: "", description: "" })
    loadRoles()
  }

  async function handleDelete(id: string) {
    await fetch(`/api/proxy/admin/roles/${id}`, { method: "DELETE" })
    loadRoles()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-[#1B3A5C]">Tag Roles</h1>
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogTrigger>
            <Button className="bg-[#2563EB]">
              <Plus className="mr-2 h-4 w-4" /> Add TagRole
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create TagRole</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-3">
              <Input
                placeholder="Role name (e.g. finance)"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
              <Input
                placeholder="Description"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
              <Button type="submit" className="w-full bg-[#2563EB]">
                Create TagRole
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-[#F9FAFB] text-left text-[#6B7280]">
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3 text-right">Users</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id} className="border-b last:border-0">
                <td className="px-4 py-3 font-medium">{role.name}</td>
                <td className="px-4 py-3 text-[#6B7280]">
                  {role.description ?? "—"}
                </td>
                <td className="px-4 py-3 text-right">{role.user_count}</td>
                <td className="px-4 py-3 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(role.id)}
                    disabled={role.name === "admin"}
                  >
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
