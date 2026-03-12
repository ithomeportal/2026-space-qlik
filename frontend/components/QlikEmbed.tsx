"use client"

import { useEffect, useRef, useState } from "react"
import { getQlikToken, startTokenRefresh, stopTokenRefresh } from "@/lib/qlik"
import { Skeleton } from "@/components/ui/skeleton"

interface QlikEmbedProps {
  appId: string
  sheetId?: string | null
}

export function QlikEmbed({ appId, sheetId }: QlikEmbedProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true

    async function init() {
      try {
        const token = await getQlikToken()
        startTokenRefresh()

        if (!mounted || !containerRef.current) return

        // Dynamically import Qlik embed web components
        await import("@qlik/embed-web-components")

        if (!mounted || !containerRef.current) return

        const tenant = process.env.NEXT_PUBLIC_QLIK_TENANT ?? "mb01txe2h9rovgh.us.qlikcloud.com"

        // Create qlik-embed element
        const embed = document.createElement("qlik-embed")
        embed.setAttribute("ui", "classic/app")
        embed.setAttribute("app-id", appId)
        if (sheetId) embed.setAttribute("sheet-id", sheetId)
        embed.setAttribute("host", `https://${tenant}`)
        embed.setAttribute("auth-type", "jwt")
        embed.setAttribute("web-integration-id", "")
        embed.setAttribute("jwt", token)
        embed.style.width = "100%"
        embed.style.height = "100%"

        containerRef.current.innerHTML = ""
        containerRef.current.appendChild(embed)
        setLoading(false)
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load dashboard")
          setLoading(false)
        }
      }
    }

    init()

    return () => {
      mounted = false
      stopTokenRefresh()
    }
  }, [appId, sheetId])

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-medium text-[#1B3A5C]">Failed to load dashboard</p>
          <p className="mt-2 text-sm text-[#6B7280]">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="relative h-full w-full">
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white">
          <div className="space-y-4 text-center">
            <Skeleton className="mx-auto h-8 w-48" />
            <Skeleton className="mx-auto h-4 w-32" />
            <p className="text-sm text-[#6B7280]">Loading dashboard...</p>
          </div>
        </div>
      )}
      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}
