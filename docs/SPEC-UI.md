# SPEC-UI: UX & Design System

## 1. Design Philosophy

Calm Technology — provides information without demanding attention, recedes when not needed.
**ONLY LIGHT MODE** — block any dark mode from the browser.

### Aesthetic References:
- **Claude.ai** — centered search bar, airy whitespace, no sidebar clutter
- **Linear.app** — sharp typography, fast interactions, keyboard-first
- **Notion** — card-based content with rich metadata
- **Apple Tablet UI** — generous touch targets, readable at distance

---

## 2. Color System

| Token | Value | Usage |
|-------|-------|-------|
| Background | `#FFFFFF` / `#F9FAFB` | White with subtle warm gray for cards |
| Primary Navy | `#1B3A5C` | Headers, primary text, logo |
| Accent Blue | `#2563EB` | Interactive elements, search focus ring, active states |
| Category — Finance | `#1D4ED8` | Dark blue pill |
| Category — HR | `#0D9488` | Teal pill |
| Category — Ops | `#D97706` | Amber pill |
| Category — Sales | `#7C3AED` | Violet pill |
| Category — Executive | `#1B3A5C` | Navy pill |
| Category — IT | `#6366F1` | Indigo pill (custom addition) |
| Text Primary | `#111827` | |
| Text Secondary | `#6B7280` | |
| Dividers | `#E5E7EB` | |

---

## 3. Typography

Font: **Inter** (via Google Fonts or next/font)

| Role | Spec |
|------|------|
| Display / Hero | Inter 700, 32–40px |
| Section Heading | Inter 600, 20–24px |
| Card Title | Inter 600, 15–16px |
| Body / Description | Inter 400, 14px |
| Badge / Label | Inter 500, 11–12px, UPPERCASE |
| Code / Monospace | JetBrains Mono 400, 13px |

---

## 4. Grid & Spacing

- Base unit: **4px**. All spacing values are multiples of 4 (8, 12, 16, 24, 32, 48, 64, 96)
- Card grid: CSS Grid with `auto-fill` columns, min 280px, max 340px, gap 24px
- Page max-width: 1280px centered with 48px horizontal padding; full-bleed on mobile
- Search bar: 640px max-width, centered, 52px height, 16px corner radius, subtle shadow on focus
- Cards: 16px corner radius, 1px border (`#E5E7EB`), 8px shadow on hover (`0 4px 24px rgba(0,0,0,0.08)`)

---

## 5. Motion & Interaction

- All transitions: **150ms ease-out** (fast enough to feel instant, long enough to feel smooth)
- Search dropdown: slides down with subtle scale transform (0.98 → 1.0)
- Card hover: lifts with 4px translateY and shadow intensification
- Page transitions: Next.js App Router shared layouts with Framer Motion layout animations
- Loading states: **skeleton screens** (not spinners) for card grids; shimmer animation at 1.5s
- Keyboard navigation: full arrow-key in search results; Escape to close modals

---

## 6. Home Screen Layout — Search-First

| Zone | Content |
|------|---------|
| **A** (top center) | Corporate logo + user avatar + notification bell |
| **B** (center) | Large, rounded search bar (placeholder: "Search reports, KPIs, departments...") |
| **C** (below search) | "Pinned" row — user's 4-6 most accessed/favorited reports as large icon cards |
| **D** (below pinned) | Categorized grid — cards organized by domain (Finance, Operations, HR, etc.) |
| **E** (bottom) | Quick-access footer links (Admin, Help, Changelog) |

### When search is focused but empty:
- Show "Recently viewed" and "Trending this week" cards

---

## 7. Report Card Design

Each card contains:

| Element | Spec |
|---------|------|
| **Report Icon / Thumbnail** | Auto-generated from category color + initials, or Qlik screenshot |
| **Report Title** | Bold, 16px, truncated at 2 lines |
| **Category Badge** | Color-coded pill (see color system) |
| **One-line Description** | Plain language: what question does this dashboard answer? |
| **Data Freshness** | "Updated 3 hours ago" — from Qlik reload metadata |
| **Owner Name** | Business owner responsible for the data, with avatar |
| **Favorite Star** | User can pin to personal top row |
| **Quick-view Button** | Hover reveals eye icon — opens 400px preview panel |
| **Open Full Screen** | Primary CTA — opens Qlik embed in full route |

---

## 8. Key Components

| Component | Responsibility |
|-----------|---------------|
| `<SearchBar />` | cmdk-based command palette. Fetches `/api/reports/search`. Shows trending when focused+empty |
| `<ReportGrid />` | React Query + CSS Grid. Groups cards by category. Supports virtualization for 200+ cards |
| `<ReportCard />` | Individual card. Hover → QuickPreview |
| `<QuickPreview />` | Radix UI Sheet (drawer) with Qlik single-sheet embed at 50% width |
| `<QlikEmbed />` | Wrapper around `<qlik-embed>`. Handles token injection and resize |
| `<RoleGuard />` | HOC that checks session roles against required role list. Redirects on failure |
| `<AdminTable />` | TanStack Table v8 with sorting, filtering, inline edit for report catalog |
| `<UsageChart />` | Recharts BarChart showing daily views per report for past 30 days |
