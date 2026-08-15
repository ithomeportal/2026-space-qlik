"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { AttritionWowContent } from "./AttritionWowContent"

export default function AttritionWowPage() {
  return (
    <ReportGuard reportKey="attrition-wow">
      <AttritionWowContent />
    </ReportGuard>
  )
}
