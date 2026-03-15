"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts"

interface UsageData {
  daily_views: Array<{ title: string; date: string; views: number }>
  top_reports: Array<{
    title: string
    category: string
    total_views: number
    unique_users: number
  }>
}

export default function AdminDashboard() {
  const [usage, setUsage] = useState<UsageData | null>(null)

  useEffect(() => {
    fetch("/api/proxy/admin/usage")
      .then((res) => res.json())
      .then((json) => {
        if (json.success) setUsage(json.data)
      })
      .catch(() => {})
  }, [])

  // Aggregate daily views for chart
  const dailyTotals =
    usage?.daily_views.reduce<Record<string, number>>((acc, row) => {
      return { ...acc, [row.date]: (acc[row.date] ?? 0) + row.views }
    }, {}) ?? {}

  const chartData = Object.entries(dailyTotals)
    .map(([date, views]) => ({ date, views }))
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-30)

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-[#1B3A5C]">Usage Dashboard</h1>

      {/* Stats cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-[#6B7280]">Total Views (30d)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold text-[#1B3A5C]">
              {usage?.daily_views.reduce((sum, r) => sum + r.views, 0) ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-[#6B7280]">Top Report</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-semibold text-[#1B3A5C]">
              {usage?.top_reports[0]?.title ?? "—"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-[#6B7280]">Active Reports</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold text-[#1B3A5C]">
              {usage?.top_reports.length ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Daily views chart */}
      <Card>
        <CardHeader>
          <CardTitle>Daily Views — Last 30 Days</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64" style={{ minWidth: 0 }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <BarChart data={chartData.length > 0 ? chartData : [{ date: "", views: 0 }]}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(val) => val.slice(5)}
                />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="views" fill="#2563EB" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Top reports table */}
      <Card>
        <CardHeader>
          <CardTitle>Top Reports</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-[#6B7280]">
                <th className="pb-2">Report</th>
                <th className="pb-2">Category</th>
                <th className="pb-2 text-right">Views</th>
                <th className="pb-2 text-right">Unique Users</th>
              </tr>
            </thead>
            <tbody>
              {usage?.top_reports.map((report) => (
                <tr key={report.title} className="border-b last:border-0">
                  <td className="py-2 font-medium">{report.title}</td>
                  <td className="py-2 text-[#6B7280]">{report.category}</td>
                  <td className="py-2 text-right">{report.total_views}</td>
                  <td className="py-2 text-right">{report.unique_users}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
