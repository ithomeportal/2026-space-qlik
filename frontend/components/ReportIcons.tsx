"use client"

import {
  Activity,
  ArrowLeftRight,
  Award,
  Banknote,
  BarChart3,
  Boxes,
  Building2,
  Calculator,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  Coins,
  Crown,
  DoorOpen,
  FileSpreadsheet,
  Gauge,
  GitCompare,
  Headphones,
  LayoutDashboard,
  LayoutGrid,
  Library,
  Medal,
  Percent,
  Phone,
  PhoneCall,
  PiggyBank,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
  Stethoscope,
  Target,
  TrendingDown,
  Store,
  TrendingUp,
  Trophy,
  Truck,
  UserCog,
  UserMinus,
  UserX,
  Users,
  Wallet,
  Wrench,
} from "lucide-react"
import type { ComponentType } from "react"
import type React from "react"

// ---------------------------------------------------------------------------
// Family palettes — each family gets a 3-stop gradient (light → mid → dark)
// rendered as one smooth diagonal sweep. Color = division/audience at a glance.
// ---------------------------------------------------------------------------

interface FamilyPalette {
  /** Lightest stop (top-left of the sweep) */
  light: string
  /** Middle stop — also the color of the corner sibling tag */
  mid: string
  /** Darkest stop (bottom-right of the sweep) — also the icon shadow base */
  dark: string
  /** Tailwind label color for screen-reader text + family hover hint */
  label: string
}

export type Family =
  | "dfw"
  | "corp"
  | "executive"
  | "operations"
  | "sales"
  | "finance"
  | "hr"
  | "it"
  | "procurement"
  | "admin"
  | "neutral"

const FAMILY_PALETTES: Record<Family, FamilyPalette> = {
  dfw:         { light: "#DBEAFE", mid: "#60A5FA", dark: "#1D4ED8", label: "DFW" },
  corp:        { light: "#EDE9FE", mid: "#A78BFA", dark: "#6D28D9", label: "CORP" },
  executive:   { light: "#E0E7FF", mid: "#6366F1", dark: "#1B3A5C", label: "Executive" },
  operations:  { light: "#FFEDD5", mid: "#FB923C", dark: "#C2410C", label: "Operations" },
  sales:       { light: "#FCE7F3", mid: "#F472B6", dark: "#BE185D", label: "Sales" },
  finance:     { light: "#D1FAE5", mid: "#34D399", dark: "#047857", label: "Finance" },
  hr:          { light: "#CCFBF1", mid: "#2DD4BF", dark: "#0F766E", label: "HR" },
  it:          { light: "#E0E7FF", mid: "#818CF8", dark: "#4338CA", label: "IT" },
  procurement: { light: "#FEF3C7", mid: "#FBBF24", dark: "#B45309", label: "Procurement" },
  admin:       { light: "#F1F5F9", mid: "#94A3B8", dark: "#1E293B", label: "Admin" },
  neutral:     { light: "#F3F4F6", mid: "#9CA3AF", dark: "#4B5563", label: "Other" },
}

/** One smooth diagonal sweep light → mid → dark (no hard bands), so the tile
 * reads as a single polished gradient. Used as inline `style.background`. */
export function familyGradient(family: Family): string {
  const p = FAMILY_PALETTES[family]
  return `linear-gradient(145deg, ${p.light} 0%, ${p.mid} 52%, ${p.dark} 100%)`
}

export function familyTagBg(family: Family): string {
  return FAMILY_PALETTES[family].dark
}

// ---------------------------------------------------------------------------
// Per-report assignments — every title has its own icon + family + optional
// sibling tag (TM1, M, Top, etc.) so visual variants are distinguishable
// without color shifts.
// ---------------------------------------------------------------------------

interface ReportIconAssignment {
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>
  family: Family
  /** Optional 2-3 char subscript tag rendered in the corner */
  tag?: string
}

const REPORT_MAP: Record<string, ReportIconAssignment> = {
  // ---- Code-made (active) ----
  "CEO Cockpit":                    { icon: Gauge,          family: "executive" },
  "eSavings from Carriers":         { icon: PiggyBank,      family: "operations" },
  "2026 Official Budget Follow Up": { icon: Target,         family: "finance" },
  "XRay CORP Mng":                  { icon: Activity,       family: "corp" },
  "XRay DFW Mng":                   { icon: Activity,       family: "dfw" },
  "XRay DFW TM1":                   { icon: Activity,       family: "dfw", tag: "TM1" },
  "XRay DFW TM2":                   { icon: Activity,       family: "dfw", tag: "TM2" },
  "XRay DFW TM3":                   { icon: Activity,       family: "dfw", tag: "TM3" },
  "XRay DFW TM4":                   { icon: Activity,       family: "dfw", tag: "TM4" },
  "CEO Executive":                  { icon: Crown,          family: "executive" },
  "HR - Access Log Doors":          { icon: DoorOpen,       family: "hr" },
  "DFW - Access Log Doors":         { icon: DoorOpen,       family: "dfw" },
  "Admin - Access Log Doors":       { icon: DoorOpen,       family: "admin" },
  "OPS - Access Log Doors":         { icon: DoorOpen,       family: "operations" },
  "Pricing - Access Log Doors":     { icon: DoorOpen,       family: "operations" },
  "Carrier Procurement - Access Log Doors":
                                    { icon: DoorOpen,       family: "procurement" },
  "HD Spot":                        { icon: Store,          family: "operations" },
  "Podium Set DFW":                 { icon: Trophy,         family: "dfw" },
  "Booker Performance Scorecard":   { icon: ClipboardCheck, family: "dfw" },
  "DFW Podium Top":                 { icon: Trophy,         family: "dfw", tag: "Top" },
  "DFW Podium Top TM1":             { icon: Trophy,         family: "dfw", tag: "TM1" },
  "DFW Podium Top TM2":             { icon: Trophy,         family: "dfw", tag: "TM2" },
  "DFW Podium Top TM3":             { icon: Trophy,         family: "dfw", tag: "TM3" },
  "DFW Podium Top TM4":             { icon: Trophy,         family: "dfw", tag: "TM4" },
  "Top Losses Lanes":               { icon: TrendingDown,   family: "executive" },
  "DFW Losses":                     { icon: TrendingDown,   family: "dfw" },
  "OPs Margins":                    { icon: Percent,        family: "operations" },
  "OPs Direct Compare":             { icon: ArrowLeftRight, family: "operations" },
  "CORP T1 Direct Compare":         { icon: ArrowLeftRight, family: "corp", tag: "T1" },
  "CORP T2 Direct Compare":         { icon: ArrowLeftRight, family: "corp", tag: "T2" },
  "CORP T3 Direct Compare":         { icon: ArrowLeftRight, family: "corp", tag: "T3" },
  "CORP T4 Direct Compare":         { icon: ArrowLeftRight, family: "corp", tag: "T4" },
  "OPs Customer Score":             { icon: ClipboardCheck, family: "operations" },
  "CORP T1 Customer Scorecard":     { icon: ClipboardCheck, family: "corp", tag: "T1" },
  "CORP T2 Customer Scorecard":     { icon: ClipboardCheck, family: "corp", tag: "T2" },
  "CORP T3 Customer Scorecard":     { icon: ClipboardCheck, family: "corp", tag: "T3" },
  "CORP T4 Customer Scorecard":     { icon: ClipboardCheck, family: "corp", tag: "T4" },
  "Sales- Attrition to OPs":        { icon: UserMinus,      family: "sales" },
  "Attrition WoW":                  { icon: UserX,          family: "executive" },
  "CORP T1 Attrition WoW":          { icon: UserX,          family: "corp", tag: "T1" },
  "CORP T2 Attrition WoW":          { icon: UserX,          family: "corp", tag: "T2" },
  "CORP T3 Attrition WoW":          { icon: UserX,          family: "corp", tag: "T3" },
  "CORP T4 Attrition WoW":          { icon: UserX,          family: "corp", tag: "T4" },
  "Track Award Loads":              { icon: Award,          family: "sales" },
  "Performance for RFPs":           { icon: LayoutDashboard, family: "sales" },
  "VoIP Calls Logs":                { icon: Phone,          family: "it" },
  "Risk Asss for Carriers":         { icon: ShieldAlert,    family: "procurement" },
  "Carrier SMS Score":              { icon: ShieldCheck,    family: "procurement" },
  "IT Tickets Mgmt":                { icon: Headphones,     family: "it" },
  "Ops Portal - Overview":          { icon: LayoutGrid,     family: "operations" },
  "CORP T1 OPS Kam Portal":         { icon: LayoutGrid,     family: "corp", tag: "T1" },
  "CORP T2 OPS Kam Portal":         { icon: LayoutGrid,     family: "corp", tag: "T2" },
  "CORP T3 OPS Kam Portal":         { icon: LayoutGrid,     family: "corp", tag: "T3" },
  "CORP T4 OPS Kam Portal":         { icon: LayoutGrid,     family: "corp", tag: "T4" },
  "Admin Aging Cashflow":           { icon: Banknote,       family: "finance" },
  "KAM Performance - DFW":          { icon: Stethoscope,    family: "dfw", tag: "KAM" },
  "Bonus Calculator":               { icon: Calculator,     family: "hr" },
  "Division Payment Calculator":    { icon: Wallet,         family: "finance" },
  "Reports Index":                  { icon: Library,        family: "executive" },

  // ---- Legacy Qlik (still in catalog) ----
  "Executive Report":               { icon: BarChart3,      family: "executive" },
  "DIRECT COMPARE":                 { icon: GitCompare,     family: "executive" },
  "DFW Executive Report":           { icon: TrendingUp,     family: "dfw" },
  "DFW X-RAY":                      { icon: ScanSearch,     family: "dfw" },
  "CORP X-RAY":                     { icon: ScanSearch,     family: "corp" },
  "Budget Follow-up":               { icon: Wallet,         family: "finance" },
  "Budget - Sales":                 { icon: Coins,          family: "finance" },
  "Customer Scorecard":             { icon: ClipboardList,  family: "operations" },
  "Carrier Savings Dashboard":      { icon: Truck,          family: "operations" },
  "Customer Attrition Detail":      { icon: UserMinus,      family: "executive" },
  "Spot Details by Express Module": { icon: FileSpreadsheet, family: "operations" },
  "RFP Performance Tracker":        { icon: LayoutDashboard, family: "sales" },
  "Attrition to Sales":             { icon: Users,          family: "sales" },
  "Attrition Week-Over-Week":       { icon: CalendarDays,   family: "executive" },
  "Awards Tracker":                 { icon: Medal,          family: "sales" },
  "HR - IT Report":                 { icon: UserCog,        family: "hr" },
  "HR Report":                      { icon: UserCog,        family: "hr" },
  "Vonage VoIP Calls":              { icon: PhoneCall,      family: "it" },
  "IT Managed Services":            { icon: Wrench,         family: "it" },
  "Available":                      { icon: Boxes,          family: "operations" },
  "CORP Executive Report":          { icon: Building2,      family: "corp" },
  "DFW Podium - Details":           { icon: Trophy,         family: "dfw", tag: "D" },
  "DFW Podium - Details TM1":       { icon: Trophy,         family: "dfw", tag: "TM1" },
  "DFW Podium - Details TM2":       { icon: Trophy,         family: "dfw", tag: "TM2" },
  "DFW Podium - Details TM3":       { icon: Trophy,         family: "dfw", tag: "TM3" },
  "DFW Podium - Details TM4":       { icon: Trophy,         family: "dfw", tag: "TM4" },
  "DFW Podium":                     { icon: Trophy,         family: "dfw" },
}

const CATEGORY_FALLBACK: Record<string, Family> = {
  Executive: "executive",
  Finance: "finance",
  Operations: "operations",
  Sales: "sales",
  HR: "hr",
  IT: "it",
  Procurement: "procurement",
  Admin: "admin",
  CORP: "corp",
  DFW: "dfw",
}

const DEFAULT_ASSIGNMENT: ReportIconAssignment = {
  icon: ShieldCheck,
  family: "neutral",
}

// ---------------------------------------------------------------------------
// Smart resolver: explicit map → mobile-strip → family-pattern → category
// ---------------------------------------------------------------------------

function inferFromTitle(title: string): ReportIconAssignment | null {
  const t = title.trim()

  // Mobile companion: "(Mob) X" → look up X, add tag="M"
  const mobMatch = t.match(/^\(Mob\)\s+(.+)$/)
  if (mobMatch) {
    const base = REPORT_MAP[mobMatch[1].trim()]
    if (base) return { ...base, tag: base.tag ? `${base.tag}·M` : "M" }
    // Fall through to pattern detection below using the un-prefixed title
  }
  const subject = mobMatch ? mobMatch[1].trim() : t

  // Sibling tag detection: trailing TMn
  const tmMatch = subject.match(/\bTM([1-4])\b/i)
  const tmTag = tmMatch ? `TM${tmMatch[1]}` : undefined
  const mobTag = mobMatch ? "M" : undefined
  const siblingTag = [tmTag, mobTag].filter(Boolean).join("·") || undefined

  // Family pattern detection by leading/contained keyword
  const upper = subject.toUpperCase()
  let family: Family | null = null
  if (/\bDFW\b/.test(upper))                     family = "dfw"
  else if (/\bCORP\b/.test(upper))                family = "corp"
  else if (/\bCEO\b|\bEXECUTIVE\b/.test(upper))   family = "executive"
  else if (/\bOPS?\b|\bOPERATIONS?\b/.test(upper)) family = "operations"
  else if (/\bSALES?\b|\bRFP\b|AWARD/.test(upper)) family = "sales"
  else if (/\bBUDGET\b|\bFINANCE\b|\bCASHFLOW\b/.test(upper)) family = "finance"
  else if (/\bHR\b/.test(upper))                  family = "hr"
  else if (/\bIT\b|\bVOIP\b/.test(upper))         family = "it"
  else if (/\bPROCUREMENT\b|\bCARRIER\b|\bRISK\b/.test(upper)) family = "procurement"
  else if (/\bADMIN\b/.test(upper))               family = "admin"

  // Icon pattern detection
  let icon: ComponentType<{ className?: string; style?: React.CSSProperties }> | null = null
  if (/PODIUM|TOP\s+\d|LEADERBOARD|AWARD/.test(upper))  icon = Trophy
  else if (/X[-\s]?RAY|MNG/.test(upper))                icon = ScanSearch
  else if (/SCORE|SCORECARD/.test(upper))               icon = ClipboardCheck
  else if (/ATTRITION/.test(upper))                     icon = UserMinus
  else if (/MARGIN/.test(upper))                        icon = Percent
  else if (/COMPARE/.test(upper))                       icon = ArrowLeftRight
  else if (/SAVINGS/.test(upper))                       icon = PiggyBank
  else if (/BUDGET|CASHFLOW|FINANCE/.test(upper))       icon = Wallet
  else if (/CALLS|VOIP|PHONE/.test(upper))              icon = Phone
  else if (/TICKET|MANAGED|SUPPORT/.test(upper))        icon = Headphones
  else if (/DOOR|ACCESS\s+LOG/.test(upper))             icon = DoorOpen
  else if (/RISK|SHIELD|SECURITY/.test(upper))          icon = ShieldAlert
  else if (/RFP|PERFORMANCE/.test(upper))               icon = LayoutDashboard
  else if (/LOSS/.test(upper))                          icon = TrendingDown
  else if (/TREND|GROWTH|UP/.test(upper))               icon = TrendingUp
  else if (/OVERVIEW|DASHBOARD/.test(upper))            icon = LayoutGrid
  else if (/REPORT|KPI/.test(upper))                    icon = BarChart3

  if (!family && !icon && !siblingTag) return null
  return {
    icon: icon ?? BarChart3,
    family: family ?? "neutral",
    tag: siblingTag,
  }
}

// ---------------------------------------------------------------------------
// Public API — keeps the original {icon, bg, fg} shape so existing callers
// keep working, and adds {family, tag, gradient} for the new tile renderer.
// ---------------------------------------------------------------------------

export interface ResolvedIcon {
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>
  family: Family
  tag?: string
  /** Inline-style smooth diagonal gradient (assign to `style.background`) */
  gradient: string
  /** Tag pill background (= family.dark) */
  tagBg: string
  /** Legacy compatibility — Tailwind gradient classes for old callers */
  bg: string
  /** Legacy compatibility — icon foreground color */
  fg: string
}

export function getReportIcon(title: string, category?: string | null): ResolvedIcon {
  const explicit = REPORT_MAP[title]
  const inferred = explicit ?? inferFromTitle(title)
  const fromCategory = category ? CATEGORY_FALLBACK[category] : undefined
  const final: ReportIconAssignment =
    inferred
    ?? (fromCategory ? { icon: BarChart3, family: fromCategory } : DEFAULT_ASSIGNMENT)

  return {
    icon: final.icon,
    family: final.family,
    tag: final.tag,
    gradient: familyGradient(final.family),
    tagBg: familyTagBg(final.family),
    // Tailwind compat — picks an approximation of the family for legacy callers
    bg: legacyTailwindBg(final.family),
    fg: "text-white",
  }
}

function legacyTailwindBg(family: Family): string {
  switch (family) {
    case "dfw":         return "from-[#60A5FA] to-[#1D4ED8]"
    case "corp":        return "from-[#A78BFA] to-[#6D28D9]"
    case "executive":   return "from-[#6366F1] to-[#1B3A5C]"
    case "operations":  return "from-[#FB923C] to-[#C2410C]"
    case "sales":       return "from-[#F472B6] to-[#BE185D]"
    case "finance":     return "from-[#34D399] to-[#047857]"
    case "hr":          return "from-[#2DD4BF] to-[#0F766E]"
    case "it":          return "from-[#818CF8] to-[#4338CA]"
    case "procurement": return "from-[#FBBF24] to-[#B45309]"
    case "admin":       return "from-[#94A3B8] to-[#1E293B]"
    default:            return "from-[#9CA3AF] to-[#4B5563]"
  }
}

// Legacy export kept for backward compat (used elsewhere in the codebase)
export const CATEGORY_COLORS: Record<string, string> = {
  Executive: "bg-[#1B3A5C]",
  Finance: "bg-[#047857]",
  Operations: "bg-[#C2410C]",
  Sales: "bg-[#BE185D]",
  HR: "bg-[#0F766E]",
  IT: "bg-[#4338CA]",
  Procurement: "bg-[#B45309]",
  Admin: "bg-[#1E293B]",
  CORP: "bg-[#6D28D9]",
  DFW: "bg-[#1D4ED8]",
}
