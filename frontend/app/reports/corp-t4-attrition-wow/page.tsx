"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { AttritionWowContent } from "../attrition-wow/AttritionWowContent"

/** CORP T4 Attrition WoW — scope-locked clone of Attrition WoW.
 *  The lock is enforced server-side by attrition_wow_team.py; `lockedTeam`
 *  is the UI half (hides the Teams controls, neutralises ?teams= / ?view=ruan). */
export default function CorpT4AttritionWowPage() {
  return (
    <ReportGuard reportKey="corp-t4-attrition-wow">
      <AttritionWowContent
        apiPrefix="custom/attrition-wow-t4"
        title="CORP T4 Attrition WoW"
        lockedTeam="TEAM4"
        badge="CORP · T4"
      />
    </ReportGuard>
  )
}
