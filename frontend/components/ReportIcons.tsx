"use client"

import {
  BarChart3,
  TrendingUp,
  DollarSign,
  Truck,
  Users,
  Monitor,
  Phone,
  Target,
  PieChart,
  Award,
  UserMinus,
  ClipboardList,
  Boxes,
  ArrowLeftRight,
  Building2,
  LayoutDashboard,
  FileSpreadsheet,
  ShieldCheck,
  DoorOpen,
  Headphones,
} from "lucide-react"
import type { ComponentType } from "react"

interface IconConfig {
  icon: ComponentType<{ className?: string }>
  bg: string
  fg: string
}

/** Map each report title to a distinctive icon + gradient-like color. */
const REPORT_ICON_MAP: Record<string, IconConfig> = {
  "Executive Report": { icon: BarChart3, bg: "from-[#1B3A5C] to-[#2563EB]", fg: "text-white" },
  "DIRECT COMPARE": { icon: ArrowLeftRight, bg: "from-[#4338CA] to-[#6366F1]", fg: "text-white" },
  "DFW Executive Report": { icon: TrendingUp, bg: "from-[#0369A1] to-[#38BDF8]", fg: "text-white" },
  "DFW X-RAY": { icon: Target, bg: "from-[#0E7490] to-[#22D3EE]", fg: "text-white" },
  "CORP X-RAY": { icon: Building2, bg: "from-[#7C3AED] to-[#A78BFA]", fg: "text-white" },
  "Budget Follow-up": { icon: DollarSign, bg: "from-[#047857] to-[#34D399]", fg: "text-white" },
  "Budget - Sales": { icon: PieChart, bg: "from-[#059669] to-[#6EE7B7]", fg: "text-white" },
  "Customer Scorecard": { icon: ClipboardList, bg: "from-[#D97706] to-[#FBBF24]", fg: "text-white" },
  "Carrier Savings Dashboard": { icon: Truck, bg: "from-[#EA580C] to-[#FB923C]", fg: "text-white" },
  "Available": { icon: Boxes, bg: "from-[#B45309] to-[#FCD34D]", fg: "text-white" },
  "Customer Attrition Detail": { icon: UserMinus, bg: "from-[#DC2626] to-[#F87171]", fg: "text-white" },
  "Spot Details by Express Module": { icon: FileSpreadsheet, bg: "from-[#C2410C] to-[#FB923C]", fg: "text-white" },
  "RFP Performance Tracker": { icon: LayoutDashboard, bg: "from-[#9333EA] to-[#C084FC]", fg: "text-white" },
  "Attrition to Sales": { icon: TrendingUp, bg: "from-[#7C3AED] to-[#DDD6FE]", fg: "text-white" },
  "Attrition Week-Over-Week": { icon: BarChart3, bg: "from-[#6D28D9] to-[#A78BFA]", fg: "text-white" },
  "Awards Tracker": { icon: Award, bg: "from-[#BE185D] to-[#F472B6]", fg: "text-white" },
  "HR - IT Report": { icon: Users, bg: "from-[#0D9488] to-[#5EEAD4]", fg: "text-white" },
  "HR - Access Log Doors": { icon: DoorOpen, bg: "from-[#0F766E] to-[#2DD4BF]", fg: "text-white" },
  "Vonage VoIP Calls": { icon: Phone, bg: "from-[#4F46E5] to-[#818CF8]", fg: "text-white" },
  "IT Managed Services": { icon: Headphones, bg: "from-[#6366F1] to-[#A5B4FC]", fg: "text-white" },
}

/** Fallback by category */
const CATEGORY_ICON_MAP: Record<string, IconConfig> = {
  Executive: { icon: BarChart3, bg: "from-[#1B3A5C] to-[#2563EB]", fg: "text-white" },
  Finance: { icon: DollarSign, bg: "from-[#047857] to-[#34D399]", fg: "text-white" },
  Operations: { icon: Truck, bg: "from-[#D97706] to-[#FBBF24]", fg: "text-white" },
  Sales: { icon: TrendingUp, bg: "from-[#7C3AED] to-[#A78BFA]", fg: "text-white" },
  HR: { icon: Users, bg: "from-[#0D9488] to-[#5EEAD4]", fg: "text-white" },
  IT: { icon: Monitor, bg: "from-[#6366F1] to-[#A5B4FC]", fg: "text-white" },
}

const DEFAULT_ICON: IconConfig = {
  icon: ShieldCheck,
  bg: "from-gray-500 to-gray-400",
  fg: "text-white",
}

export function getReportIcon(title: string, category?: string | null): IconConfig {
  return (
    REPORT_ICON_MAP[title] ??
    CATEGORY_ICON_MAP[category ?? ""] ??
    DEFAULT_ICON
  )
}

export const CATEGORY_COLORS: Record<string, string> = {
  Executive: "bg-[#1B3A5C]",
  Finance: "bg-[#047857]",
  Operations: "bg-[#D97706]",
  Sales: "bg-[#7C3AED]",
  HR: "bg-[#0D9488]",
  IT: "bg-[#6366F1]",
}
