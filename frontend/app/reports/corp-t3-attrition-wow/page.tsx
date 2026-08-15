"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { AttritionWowContent } from "../attrition-wow/AttritionWowContent"

/** CORP T3 Attrition WoW — scope-locked clone of Attrition WoW.
 *  The lock is enforced server-side by attrition_wow_team.py; `lockedTeam`
 *  is the UI half (hides the Teams controls, neutralises ?teams= / ?view=ruan). */
export default function CorpT3AttritionWowPage() {
  return (
    <ReportGuard reportKey="corp-t3-attrition-wow">
      <AttritionWowContent
        apiPrefix="custom/attrition-wow-t3"
        title="CORP T3 Attrition WoW"
        lockedTeam="TEAM3"
        badge="CORP · T3"
      />
    </ReportGuard>
  )
}
