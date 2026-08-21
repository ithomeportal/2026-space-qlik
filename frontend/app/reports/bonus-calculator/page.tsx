"use client"

import { BonusCalculatorPage } from "@/components/BonusCalculatorContent"

/**
 * Bonus Calculator (corporate).
 *
 * The shell lives in components/ because Next.js allows a page.tsx to export
 * only its default — and the DFW copy (Bruno PDF 2026-08-20) needs the same
 * component with a different apiPrefix and report key.
 */
export default function CorporateBonusCalculatorPage() {
  return <BonusCalculatorPage />
}
