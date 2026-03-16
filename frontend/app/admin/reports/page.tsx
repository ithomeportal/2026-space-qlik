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
import { Plus, Trash2, Pencil, FileEdit } from "lucide-react"

interface Report {
  id: string
  title: string
  description: string | null
  note: string | null
  qlik_app_id: string
  qlik_sheet_id: string | null
  is_active: boolean
  views_30d: number
  tag_roles: string[]
}

interface Role {
  id: string
  name: string
}

export default function AdminReportsPage() {
  const [reports, setReports] = useState<Report[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [editingReport, setEditingReport] = useState<Report | null>(null)
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [editReport, setEditReport] = useState<Report | null>(null)
  const [editForm, setEditForm] = useState({ title: "", description: "", note: "" })
  const [form, setForm] = useState({
    title: "",
    description: "",
    note: "",
    qlik_app_id: "",
    qlik_sheet_id: "",
    owner_name: "",
    tags: "",
  })
  const [createRoles, setCreateRoles] = useState<string[]>([])

  useEffect(() => {
    loadReports()
    loadRoles()
  }, [])

  async function loadReports() {
    const res = await fetch("/api/proxy/admin/reports?limit=200")
    const json = await res.json()
    if (json.success) setReports(json.data)
  }

  async function loadRoles() {
    const res = await fetch("/api/proxy/admin/roles")
    const json = await res.json()
    if (json.success) setRoles(json.data)
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    await fetch("/api/proxy/admin/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...form,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        role_names: createRoles,
      }),
    })
    setShowCreate(false)
    setForm({
      title: "",
      description: "",
      note: "",
      qlik_app_id: "",
      qlik_sheet_id: "",
      owner_name: "",
      tags: "",
    })
    setCreateRoles([])
    loadReports()
  }

  async function handleDelete(id: string) {
    await fetch(`/api/proxy/admin/reports/${id}`, { method: "DELETE" })
    loadReports()
  }

  function openEditReport(report: Report) {
    setEditReport(report)
    setEditForm({
      title: report.title,
      description: report.description ?? "",
      note: report.note ?? "",
    })
  }

  async function handleSaveEdit() {
    if (!editReport) return
    await fetch(`/api/proxy/admin/reports/${editReport.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: editForm.title || undefined,
        description: editForm.description || undefined,
        note: editForm.note || undefined,
      }),
    })
    setEditReport(null)
    loadReports()
  }

  function openEditRoles(report: Report) {
    setEditingReport(report)
    setSelectedRoles(report.tag_roles ?? [])
  }

  async function handleSaveRoles() {
    if (!editingReport) return
    await fetch(`/api/proxy/admin/reports/${editingReport.id}/roles`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role_names: selectedRoles }),
    })
    setEditingReport(null)
    loadReports()
  }

  function toggleRole(roleName: string, list: string[], setList: (v: string[]) => void) {
    if (list.includes(roleName)) {
      setList(list.filter((r) => r !== roleName))
    } else {
      setList([...list, roleName])
    }
  }

  function RoleCheckboxes({
    selected,
    onChange,
  }: {
    selected: string[]
    onChange: (roleName: string) => void
  }) {
    return (
      <div className="flex flex-wrap gap-2">
        {roles.map((role) => (
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
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-[#1B3A5C]">Report Catalog</h1>
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogTrigger>
            <Button className="bg-[#2563EB]">
              <Plus className="mr-2 h-4 w-4" /> Add Report
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New Report</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-3">
              <Input
                placeholder="Title"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
              />
              <Input
                placeholder="Description"
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
              <textarea
                placeholder="Note — additional details about what this report contains"
                value={form.note}
                onChange={(e) =>
                  setForm({ ...form, note: e.target.value })
                }
                rows={3}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Input
                placeholder="Qlik App ID"
                value={form.qlik_app_id}
                onChange={(e) =>
                  setForm({ ...form, qlik_app_id: e.target.value })
                }
                required
              />
              <Input
                placeholder="Qlik Sheet ID"
                value={form.qlik_sheet_id}
                onChange={(e) =>
                  setForm({ ...form, qlik_sheet_id: e.target.value })
                }
              />
              <Input
                placeholder="Owner Name"
                value={form.owner_name}
                onChange={(e) =>
                  setForm({ ...form, owner_name: e.target.value })
                }
              />
              <Input
                placeholder="Tags (comma-separated)"
                value={form.tags}
                onChange={(e) => setForm({ ...form, tags: e.target.value })}
              />
              <div>
                <p className="mb-2 text-sm font-medium text-[#374151]">
                  Tag Roles (who can access)
                </p>
                <RoleCheckboxes
                  selected={createRoles}
                  onChange={(name) =>
                    toggleRole(name, createRoles, setCreateRoles)
                  }
                />
              </div>
              <Button type="submit" className="w-full bg-[#2563EB]">
                Create Report
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Edit Tag Roles Dialog */}
      <Dialog
        open={!!editingReport}
        onOpenChange={(open) => !open && setEditingReport(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Edit Tag Roles — {editingReport?.title}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-[#6B7280]">
              Select which Tag Roles can access this report:
            </p>
            <RoleCheckboxes
              selected={selectedRoles}
              onChange={(name) =>
                toggleRole(name, selectedRoles, setSelectedRoles)
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

      {/* Edit Report Dialog */}
      <Dialog
        open={!!editReport}
        onOpenChange={(open) => !open && setEditReport(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Edit Report — {editReport?.title}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="Title"
              value={editForm.title}
              onChange={(e) =>
                setEditForm({ ...editForm, title: e.target.value })
              }
            />
            <Input
              placeholder="Description"
              value={editForm.description}
              onChange={(e) =>
                setEditForm({ ...editForm, description: e.target.value })
              }
            />
            <div>
              <label className="mb-1 block text-sm font-medium text-[#374151]">
                Note
              </label>
              <textarea
                placeholder="Additional details about what this report contains"
                value={editForm.note}
                onChange={(e) =>
                  setEditForm({ ...editForm, note: e.target.value })
                }
                rows={4}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
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
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Tag Roles</th>
              <th className="px-4 py-3">App ID</th>
              <th className="px-4 py-3 text-right">Views (30d)</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((report) => (
              <tr key={report.id} className="border-b last:border-0">
                <td className="px-4 py-3 font-medium">{report.title}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {(report.tag_roles ?? []).map((role) => (
                      <Badge
                        key={role}
                        variant="secondary"
                        className="text-xs"
                      >
                        {role}
                      </Badge>
                    ))}
                    {(!report.tag_roles || report.tag_roles.length === 0) && (
                      <span className="text-xs text-[#9CA3AF]">None</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-[#6B7280]">
                  {report.qlik_app_id.slice(0, 8)}...
                </td>
                <td className="px-4 py-3 text-right">{report.views_30d}</td>
                <td className="px-4 py-3">
                  <Badge
                    variant={report.is_active ? "default" : "secondary"}
                  >
                    {report.is_active ? "Active" : "Inactive"}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditReport(report)}
                      title="Edit Report"
                    >
                      <FileEdit className="h-4 w-4 text-[#2563EB]" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditRoles(report)}
                      title="Edit Tag Roles"
                    >
                      <Pencil className="h-4 w-4 text-[#6B7280]" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(report.id)}
                      title="Delete Report"
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
