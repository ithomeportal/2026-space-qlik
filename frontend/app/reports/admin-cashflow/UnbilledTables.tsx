"use client"

import type { AdminCashflowFilters } from "@/lib/admin-cashflow-api"
import { DeliveredNotBilledCard } from "./DeliveredNotBilledCard"
import { ReadyNotBilledCard } from "./ReadyNotBilledCard"

interface Props {
  filters: AdminCashflowFilters
  // Bruno (PDF 2026-08-27) R1: click a customer name to filter the page.
  onCustomerClick?: (name: string) => void
}

// Bruno Aging R2 + R3 (2026-06-11): each card now carries per-column Order /
// Customer free-text filters and an "Expand" pop-up that pages through every
// order. The card bodies live in their own files (DeliveredNotBilledCard /
// ReadyNotBilledCard); shared chrome is in UnbilledShared.
export function UnbilledTables({ filters, onCustomerClick }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <DeliveredNotBilledCard filters={filters} onCustomerClick={onCustomerClick} />
      <ReadyNotBilledCard filters={filters} onCustomerClick={onCustomerClick} />
    </div>
  )
}
