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
import { Plus, Trash2, Pencil } from "lucide-react"

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
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [editForm, setEditForm] = useState({ name: "", description: "" })
  const [error, setError] = useState<string | null>(null)

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
    setError(null)
    const res = await fetch("/api/proxy/admin/roles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    })
    const json = await res.json()
    if (!res.ok || !json.success) {
      setError(json.detail || json.error || "Failed to create TagRole")
      return
    }
    setShowCreate(false)
    setForm({ name: "", description: "" })
    setError(null)
    loadRoles()
  }

  async function handleDelete(id: string) {
    await fetch(`/api/proxy/admin/roles/${id}`, { method: "DELETE" })
    loadRoles()
  }

  function openEdit(role: Role) {
    setEditingRole(role)
    setEditForm({ name: role.name, description: role.description ?? "" })
    setError(null)
  }

  async function handleSaveEdit() {
    if (!editingRole) return
    setError(null)
    const res = await fetch(`/api/proxy/admin/roles/${editingRole.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: editForm.name !== editingRole.name ? editForm.name : undefined,
        description: editForm.description,
      }),
    })
    const json = await res.json()
    if (!res.ok || !json.success) {
      setError(json.detail || json.error || "Failed to update TagRole")
      return
    }
    setEditingRole(null)
    setError(null)
    loadRoles()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-[#1B3A5C]">Tag Roles</h1>
        <Dialog
          open={showCreate}
          onOpenChange={(open) => {
            setShowCreate(open)
            if (!open) setError(null)
          }}
        >
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
                placeholder="TagRole name (e.g. finance)"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
              <Input
                placeholder="Description"
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
              {error && (
                <p className="text-sm text-red-500">{error}</p>
              )}
              <Button type="submit" className="w-full bg-[#2563EB]">
                Create TagRole
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Edit TagRole Dialog */}
      <Dialog
        open={!!editingRole}
        onOpenChange={(open) => {
          if (!open) {
            setEditingRole(null)
            setError(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit TagRole</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-[#374151]">
                Name
              </label>
              <Input
                value={editForm.name}
                onChange={(e) =>
                  setEditForm({ ...editForm, name: e.target.value })
                }
                disabled={editingRole?.name === "admin"}
              />
              {editingRole?.name === "admin" && (
                <p className="mt-1 text-xs text-[#9CA3AF]">
                  The admin TagRole cannot be renamed
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-[#374151]">
                Description
              </label>
              <Input
                value={editForm.description}
                onChange={(e) =>
                  setEditForm({ ...editForm, description: e.target.value })
                }
                placeholder="Description"
              />
            </div>
            {error && (
              <p className="text-sm text-red-500">{error}</p>
            )}
            <Button
              onClick={handleSaveEdit}
              className="w-full bg-[#2563EB]"
            >
              Save Changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <div className="rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-[#F9FAFB] text-left text-[#6B7280]">
              <th className="px-4 py-3">TagRole</th>
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
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEdit(role)}
                      title="Edit TagRole"
                    >
                      <Pencil className="h-4 w-4 text-[#6B7280]" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(role.id)}
                      disabled={role.name === "admin"}
                      title="Delete TagRole"
                    >
                      <Trash2 className="h-4 w-4 text-red-500" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
