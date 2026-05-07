/**
 * Per-report TagRole allow-lists for code-made (custom) reports.
 *
 * Backend is the source of truth — these mirror the `roles` array
 * of each entry in `backend/app/services/seed.py::CUSTOM_REPORTS`
 * and the `*_ROLES` constant of each report's router under
 * `backend/app/routers/`. Keep all three in sync when adjusting
 * access. Backend gating is enforced via `require_tag_role(...)`;
 * these arrays drive the front-end <RoleGuard /> so users without
 * an allowed TagRole see a single clean access-denied banner
 * instead of every panel surfacing its own 403 error.
 *
 * Match is case-insensitive on both sides; admin always bypasses.
 */
export const REPORT_ACCESS = {
  "esavings-carriers": ["CEO", "Executive", "Procurement", "Finance", "CORP"],
  "budget-followup-2026": ["CEO", "Executive", "Operations", "Finance", "CORP", "DFW"],
  "xray-corp-mng": ["CEO", "Executive", "CORP", "Operations", "Finance"],
  "xray-dfw-mng": ["CEO", "Executive", "DFW", "Operations", "Finance"],
  "xray-dfw-tm1": ["DFW-TM1", "CEO", "Executive"],
  "xray-dfw-tm2": ["DFW-TM2", "CEO", "Executive"],
  "xray-dfw-tm3": ["DFW-TM3", "CEO", "Executive"],
  "xray-dfw-tm4": ["DFW-TM4", "CEO", "Executive"],
  "ceo-executive": ["CEO"],
  "hr-access-doors": ["CEO", "Executive", "HR", "IT"],
  "dfw-access-doors": ["DFW", "DFW-Assistent", "DFW KAM", "Assitent OPs manager"],
  "podium-dfw": ["DFW"],
  "dfw-podium-top": ["DFW"],
  "losses-lanes": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
  "ops-margins": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
  "ops-direct-compare": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
  "ops-customer-score": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
  "sales-attrition-to-ops": ["CEO", "Executive", "Sales", "CORP", "DFW", "Operations", "Finance"],
  "attrition-wow": ["CEO", "Executive", "Sales", "CORP", "DFW", "Operations", "Finance"],
  "voip-calls-logs": [
    "CEO",
    "Executive",
    "Procurement",
    "Finance",
    "Operations",
    "Sales",
    "HR",
    "IT",
    "DFW",
    "CORP",
  ],
  "track-award-loads": [
    "CEO",
    "Executive",
    "Sales",
    "Procurement",
    "Operations",
    "Finance",
    "CORP",
    "DFW",
  ],
  "rfp-performance": [
    "CEO",
    "Executive",
    "Sales",
    "Procurement",
    "CORP",
    "DFW",
    "Operations",
    "Finance",
  ],
  "carrier-risk": [
    "CEO",
    "Executive",
    "Procurement",
    "CORP",
    "DFW",
    "Operations",
    "Finance",
  ],
  "it-tickets-mgmt": [
    "CEO",
    "Executive",
    "Procurement",
    "Finance",
    "Operations",
    "Sales",
    "HR",
    "IT",
    "DFW",
    "CORP",
  ],
  "admin-cashflow": [
    "CEO",
    "Executive",
    "Finance",
    "CORP",
    "DFW",
    "Operations",
    "AdminFinance",
  ],
} as const

export type ReportKey = keyof typeof REPORT_ACCESS
