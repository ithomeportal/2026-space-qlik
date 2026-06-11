"use client"

import type { AdminCashflowFilters } from "@/lib/admin-cashflow-api"
import { DeliveredNotBilledCard } from "./DeliveredNotBilledCard"
import { ReadyNotBilledCard } from "./ReadyNotBilledCard"

interface Props {
  filters: AdminCashflowFilters
}

// Bruno Aging R2 + R3 (2026-06-11): each card now carries per-column Order /
// Customer free-text filters and an "Expand" pop-up that pages through every
// order. The card bodies live in their own files (DeliveredNotBilledCard /
// ReadyNotBilledCard); shared chrome is in UnbilledShared.
export function UnbilledTables({ filters }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <DeliveredNotBilledCard filters={filters} />
      <ReadyNotBilledCard filters={filters} />
    </div>
  )
}
