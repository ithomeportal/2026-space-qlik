"use client"

import { AllOrdersTable } from "./AllOrdersTable"
import { XrayDfwErrorBanner } from "../ErrorBanner"
import { useState } from "react"
import type { XrayDfwFilters } from "@/lib/xray-dfw-api"

/**
 * GM tab — Bruno PDF 2026-09-15 ("space - XRAY DFW Updates").
 *
 * R1 the tab, pinned to `customer_name = 'GM C/O CTSI'`
 * R2 the Contract vs Spot "All Orders" table, duplicated here
 * R3 without the `total_charge <> 0` filter — every order shows
 * R4 plus BOL (`blnum`) and PO (`po`) from `mcleod_gld_customer_view`
 * R5 ordered Order DESC, then PO DESC
 *
 * ⚠ The customer pin REPLACES the page's customer multi-select rather than
 * intersecting with it. Intersecting would let the global Customer filter
 * empty a tab whose entire purpose is one customer, and the empty table would
 * read as "GM stopped shipping". Every other filter — range, sub-team, lane,
 * contract type, equipment — still applies, so the Range bar above still
 * drives this tab.
 *
 * The DFW scope the report already carries costs nothing here: all 34,868 GM
 * orders in v4 sit inside TM1-TM5 (measured 2026-09-15), so `team_id =
 * 'TEAM-DFW'` removes none of them.
 */
const GM_CUSTOMER = "GM C/O CTSI"

interface Props {
  filters: XrayDfwFilters
  onLaneClick?: (lane: string) => void
}

export function Gm({ filters, onLaneClick }: Props) {
  const [err, setErr] = useState<unknown>(null)

  // ⚠ `customers` is REPLACED, never merged — see the note above. `view` is
  // dropped too: the RUAN view swaps the grouping column to `client`, and a
  // tab keyed on a customer_name would then filter on a column it is not
  // reading.
  const gmFilters: XrayDfwFilters = {
    ...filters,
    customers: [GM_CUSTOMER],
    view: undefined,
  }

  return (
    <div className="space-y-6">
      <XrayDfwErrorBanner label="GM" errors={[err]} />
      <p className="text-xs text-[#6B7280]">
        Every order for <span className="font-semibold text-[#111827]">{GM_CUSTOMER}</span>{" "}
        in the selected range — including orders that have not been billed yet.
      </p>
      <AllOrdersTable
        filters={gmFilters}
        entityLabel="Customer"
        onLaneClick={onLaneClick}
        sort="order_desc"
        sortLabel="Order, then PO, descending"
        showRefs
        includeZeroCharge
        onError={setErr}
      />
    </div>
  )
}
