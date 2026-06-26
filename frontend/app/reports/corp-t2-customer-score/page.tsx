"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { CustomerScoreContent } from "@/components/CustomerScoreContent"

export default function CorpT2CustomerScorePage() {
  return (
    <ReportGuard reportKey="corp-t2-customer-score">
      <CustomerScoreContent
        apiPrefix="custom/ops-customer-score-t2"
        title="CORP T2 Customer Scorecard"
        lockedTeam="TEAM2"
        badge="CORP · T2"
      />
    </ReportGuard>
  )
}
