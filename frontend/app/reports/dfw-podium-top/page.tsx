"use client"

import { DfwPodiumTopContent } from "@/components/DfwPodiumTopContent"

export default function DfwPodiumTopPage() {
  return (
    <DfwPodiumTopContent
      reportKey="dfw-podium-top"
      apiPrefix="custom/dfw-podium-top"
      title="DFW Podium Top"
    />
  )
}
