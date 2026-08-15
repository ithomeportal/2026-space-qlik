"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { AttritionWowContent } from "../attrition-wow/AttritionWowContent"

/** CORP T1 Attrition WoW — scope-locked clone of Attrition WoW.
 *  The lock is enforced server-side by attrition_wow_team.py; `lockedTeam`
 *  is the UI half (hides the Teams controls, neutralises ?teams= / ?view=ruan). */
export default function CorpT1AttritionWowPage() {
  return (
    <ReportGuard reportKey="corp-t1-attrition-wow">
      <AttritionWowContent
        apiPrefix="custom/attrition-wow-t1"
        title="CORP T1 Attrition WoW"
        lockedTeam="TEAM1"
        badge="CORP · T1"
      />
    </ReportGuard>
  )
}
