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
import { Plus, Trash2 } from "lucide-react"

interface Report {
  id: string
  title: string
  category: string | null
  qlik_app_id: string
  qlik_sheet_id: string | null
  is_active: boolean
  views_30d: number
}

export default function AdminReportsPage() {
  const [reports, setReports] = useState<Report[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({
    title: "",
    description: "",
    category: "",
    qlik_app_id: "",
    qlik_sheet_id: "",
    owner_name: "",
    tags: "",
  })

  useEffect(() => {
    loadReports()
  }, [])

  async function loadReports() {
    const res = await fetch("/api/proxy/admin/reports")
    const json = await res.json()
    if (json.success) setReports(json.data)
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    await fetch("/api/proxy/admin/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...form,
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    })
    setShowCreate(false)
    setForm({ title: "", description: "", category: "", qlik_app_id: "", qlik_sheet_id: "", owner_name: "", tags: "" })
    loadReports()
  }

  async function handleDelete(id: string) {
    await fetch(`/api/proxy/admin/reports/${id}`, { method: "DELETE" })
    loadReports()
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
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
              <Input
                placeholder="Category (Executive, Finance, etc.)"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
              />
              <Input
                placeholder="Qlik App ID"
                value={form.qlik_app_id}
                onChange={(e) => setForm({ ...form, qlik_app_id: e.target.value })}
                required
              />
              <Input
                placeholder="Qlik Sheet ID"
                value={form.qlik_sheet_id}
                onChange={(e) => setForm({ ...form, qlik_sheet_id: e.target.value })}
              />
              <Input
                placeholder="Owner Name"
                value={form.owner_name}
                onChange={(e) => setForm({ ...form, owner_name: e.target.value })}
              />
              <Input
                placeholder="Tags (comma-separated)"
                value={form.tags}
                onChange={(e) => setForm({ ...form, tags: e.target.value })}
              />
              <Button type="submit" className="w-full bg-[#2563EB]">
                Create Report
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-[#F9FAFB] text-left text-[#6B7280]">
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Category</th>
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
                  {report.category && (
                    <Badge variant="secondary">{report.category}</Badge>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-[#6B7280]">
                  {report.qlik_app_id.slice(0, 8)}...
                </td>
                <td className="px-4 py-3 text-right">{report.views_30d}</td>
                <td className="px-4 py-3">
                  <Badge variant={report.is_active ? "default" : "secondary"}>
                    {report.is_active ? "Active" : "Inactive"}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(report.id)}
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
