"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Plus, Trash2, Pencil, ExternalLink } from "lucide-react"

interface App {
  id: string
  title: string
  url: string
  description: string | null
  is_active: boolean
  tag_roles: string[]
}

interface Role {
  id: string
  name: string
}

export default function AdminAppsPage() {
  const [apps, setApps] = useState<App[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [editingApp, setEditingApp] = useState<App | null>(null)
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [allSelected, setAllSelected] = useState(false)
  const [form, setForm] = useState({
    title: "",
    url: "",
    description: "",
  })
  const [createRoles, setCreateRoles] = useState<string[]>([])
  const [createAll, setCreateAll] = useState(false)

  useEffect(() => {
    loadApps()
    loadRoles()
  }, [])

  async function loadApps() {
    const res = await fetch("/api/proxy/admin/apps")
    const json = await res.json()
    if (json.success) setApps(json.data)
  }

  async function loadRoles() {
    const res = await fetch("/api/proxy/admin/roles")
    const json = await res.json()
    if (json.success) setRoles(json.data)
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    const roleNames = createAll
      ? roles.filter((r) => r.name !== "admin").map((r) => r.name)
      : createRoles
    await fetch("/api/proxy/admin/apps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, role_names: roleNames }),
    })
    setShowCreate(false)
    setForm({ title: "", url: "", description: "" })
    setCreateRoles([])
    setCreateAll(false)
    loadApps()
  }

  async function handleDelete(id: string) {
    await fetch(`/api/proxy/admin/apps/${id}`, { method: "DELETE" })
    loadApps()
  }

  function openEditRoles(app: App) {
    setEditingApp(app)
    const nonAdminRoles = roles
      .filter((r) => r.name !== "admin")
      .map((r) => r.name)
    const appRoles = app.tag_roles ?? []
    setSelectedRoles(appRoles)
    setAllSelected(
      nonAdminRoles.length > 0 &&
        nonAdminRoles.every((r) => appRoles.includes(r))
    )
  }

  async function handleSaveRoles() {
    if (!editingApp) return
    const roleNames = allSelected
      ? roles.filter((r) => r.name !== "admin").map((r) => r.name)
      : selectedRoles
    await fetch(`/api/proxy/admin/apps/${editingApp.id}/roles`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role_names: roleNames }),
    })
    setEditingApp(null)
    loadApps()
  }

  function toggleRole(
    roleName: string,
    list: string[],
    setList: (v: string[]) => void,
    setAll: (v: boolean) => void
  ) {
    const updated = list.includes(roleName)
      ? list.filter((r) => r !== roleName)
      : [...list, roleName]
    setList(updated)
    const nonAdmin = roles.filter((r) => r.name !== "admin").map((r) => r.name)
    setAll(nonAdmin.every((r) => updated.includes(r)))
  }

  function handleToggleAll(
    checked: boolean,
    setList: (v: string[]) => void,
    setAll: (v: boolean) => void
  ) {
    setAll(checked)
    if (checked) {
      setList(roles.filter((r) => r.name !== "admin").map((r) => r.name))
    } else {
      setList([])
    }
  }

  function RoleSelector({
    selected,
    onChange,
    isAll,
    onToggleAll,
  }: {
    selected: string[]
    onChange: (name: string) => void
    isAll: boolean
    onToggleAll: (checked: boolean) => void
  }) {
    return (
      <div className="space-y-2">
        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-[#E5E7EB] px-3 py-2 text-sm hover:bg-[#F9FAFB]">
          <input
            type="checkbox"
            checked={isAll}
            onChange={(e) => onToggleAll(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-[#2563EB]"
          />
          <span className="font-medium">All TagRoles</span>
        </label>
        <div className="flex flex-wrap gap-2">
          {roles
            .filter((r) => r.name !== "admin")
            .map((role) => (
              <label
                key={role.id}
                className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                  selected.includes(role.name)
                    ? "border-[#2563EB] bg-[#EFF6FF] text-[#2563EB]"
                    : "border-[#E5E7EB] text-[#6B7280] hover:border-[#9CA3AF]"
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={selected.includes(role.name)}
                  onChange={() => onChange(role.name)}
                />
                {role.name}
              </label>
            ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-[#1B3A5C]">Apps</h1>
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogTrigger>
            <Button className="bg-[#2563EB]">
              <Plus className="mr-2 h-4 w-4" /> Add App
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New App</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-3">
              <Input
                placeholder="App name (e.g. Legal Contracts)"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
              />
              <Input
                placeholder="URL (e.g. https://legaldms.unilinkportal.com/)"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                required
                type="url"
              />
              <Input
                placeholder="Description (optional)"
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
              <div>
                <p className="mb-2 text-sm font-medium text-[#374151]">
                  Tag Roles (who can access)
                </p>
                <RoleSelector
                  selected={createRoles}
                  onChange={(name) =>
                    toggleRole(name, createRoles, setCreateRoles, setCreateAll)
                  }
                  isAll={createAll}
                  onToggleAll={(checked) =>
                    handleToggleAll(checked, setCreateRoles, setCreateAll)
                  }
                />
              </div>
              <Button type="submit" className="w-full bg-[#2563EB]">
                Create App
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <p className="text-sm text-[#6B7280]">
        Apps are external links that open in a new browser tab. Users see them on
        the home page based on their Tag Roles.
      </p>

      {/* Edit TagRoles Dialog */}
      <Dialog
        open={!!editingApp}
        onOpenChange={(open) => !open && setEditingApp(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Tag Roles — {editingApp?.title}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <RoleSelector
              selected={selectedRoles}
              onChange={(name) =>
                toggleRole(
                  name,
                  selectedRoles,
                  setSelectedRoles,
                  setAllSelected
                )
              }
              isAll={allSelected}
              onToggleAll={(checked) =>
                handleToggleAll(checked, setSelectedRoles, setAllSelected)
              }
            />
            <Button
              onClick={handleSaveRoles}
              className="w-full bg-[#2563EB]"
            >
              Save Tag Roles
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <div className="rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-[#F9FAFB] text-left text-[#6B7280]">
              <th className="px-4 py-3">App Name</th>
              <th className="px-4 py-3">URL</th>
              <th className="px-4 py-3">Tag Roles</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {apps.map((app) => (
              <tr key={app.id} className="border-b last:border-0">
                <td className="px-4 py-3 font-medium">{app.title}</td>
                <td className="px-4 py-3">
                  <a
                    href={app.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-[#2563EB] hover:underline"
                  >
                    {new URL(app.url).hostname}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {(app.tag_roles ?? []).map((role) => (
                      <Badge
                        key={role}
                        variant="secondary"
                        className="text-xs"
                      >
                        {role}
                      </Badge>
                    ))}
                    {(!app.tag_roles || app.tag_roles.length === 0) && (
                      <span className="text-xs text-[#9CA3AF]">None</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge variant={app.is_active ? "default" : "secondary"}>
                    {app.is_active ? "Active" : "Inactive"}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditRoles(app)}
                      title="Edit Tag Roles"
                    >
                      <Pencil className="h-4 w-4 text-[#6B7280]" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(app.id)}
                      title="Delete App"
                    >
                      <Trash2 className="h-4 w-4 text-red-500" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {apps.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-[#9CA3AF]"
                >
                  No apps yet. Click &ldquo;Add App&rdquo; to create one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
