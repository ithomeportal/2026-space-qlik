"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { AttritionWowContent } from "../attrition-wow/AttritionWowContent"

/** CORP T2 Attrition WoW — scope-locked clone of Attrition WoW.
 *  The lock is enforced server-side by attrition_wow_team.py; `lockedTeam`
 *  is the UI half (hides the Teams controls, neutralises ?teams= / ?view=ruan). */
export default function CorpT2AttritionWowPage() {
  return (
    <ReportGuard reportKey="corp-t2-attrition-wow">
      <AttritionWowContent
        apiPrefix="custom/attrition-wow-t2"
        title="CORP T2 Attrition WoW"
        lockedTeam="TEAM2"
        badge="CORP · T2"
      />
    </ReportGuard>
  )
}
