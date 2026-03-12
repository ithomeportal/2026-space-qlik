"use client"

import { useEffect, useRef, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"

interface QlikEmbedProps {
  appId: string
  sheetId?: string | null
}

const TENANT = process.env.NEXT_PUBLIC_QLIK_TENANT ?? "mb01txe2h9rovgh.us.qlikcloud.com"
const TENANT_URL = `https://${TENANT}`

let qlikScriptLoaded = false

/**
 * Loads the Qlik embed script from CDN with cookie auth + getAccessToken.
 * The script registers a service worker that intercepts requests to the
 * tenant and injects the JWT returned by our getAccessToken function.
 */
async function loadQlikScript(): Promise<void> {
  if (qlikScriptLoaded) return

  // Fetch JWT from our backend proxy
  const res = await fetch("/api/proxy/qlik/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error("Failed to fetch Qlik token")
  const json = await res.json()
  const token = json.data.token

  // Expose getAccessToken globally for the Qlik embed script
  ;(window as unknown as Record<string, unknown>).__qlikToken = token
  ;(window as unknown as Record<string, unknown>).getQlikAccessToken = () => {
    return (window as unknown as Record<string, unknown>).__qlikToken as string
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script")
    script.crossOrigin = "anonymous"
    script.type = "application/javascript"
    script.src = `${TENANT_URL}/resources/assets/external/requirejs/require.js`
    script.dataset.host = TENANT_URL
    script.dataset.authType = "cookie"
    script.dataset.getAccessToken = "getQlikAccessToken"
    script.dataset.crossSiteCookies = "true"
    script.onload = () => {
      qlikScriptLoaded = true
      resolve()
    }
    script.onerror = () => reject(new Error("Failed to load Qlik embed script"))
    document.head.appendChild(script)
  })
}

// Refresh token periodically
let refreshInterval: ReturnType<typeof setInterval> | null = null

function startTokenRefresh() {
  if (refreshInterval) return
  refreshInterval = setInterval(async () => {
    try {
      const res = await fetch("/api/proxy/qlik/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      if (res.ok) {
        const json = await res.json()
        ;(window as unknown as Record<string, unknown>).__qlikToken = json.data.token
      }
    } catch {
      // Silently retry next interval
    }
  }, 50 * 60 * 1000)
}

function stopTokenRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

export function QlikEmbed({ appId, sheetId }: QlikEmbedProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true

    async function init() {
      try {
        await loadQlikScript()
        startTokenRefresh()

        if (!mounted || !containerRef.current) return

        const embed = document.createElement("qlik-embed")
        embed.setAttribute("ui", "classic/app")
        embed.setAttribute("app-id", appId)
        if (sheetId) embed.setAttribute("sheet-id", sheetId)
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
