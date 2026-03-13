"use client"

import { useEffect, useRef, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"

interface QlikEmbedProps {
  appId: string
  sheetId?: string | null
}

const TENANT = process.env.NEXT_PUBLIC_QLIK_TENANT ?? "mb01txe2h9rovgh.us.qlikcloud.com"
const TENANT_URL = `https://${TENANT}`
const WEB_INTEGRATION_ID = process.env.NEXT_PUBLIC_QLIK_WEB_INTEGRATION_ID ?? "UcOYHRHZf7W4ydusUB3cJPin3HHOPnit"

async function fetchToken(): Promise<string> {
  const res = await fetch("/api/proxy/qlik/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error("Failed to fetch Qlik token")
  const json = await res.json()
  return json.data.token
}

let refreshInterval: ReturnType<typeof setInterval> | null = null
let currentToken: string | null = null
let configInjected = false

function startTokenRefresh() {
  if (refreshInterval) return
  refreshInterval = setInterval(async () => {
    try {
      currentToken = await fetchToken()
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

/**
 * Inject a global <script type="qlik-embed/config"> tag once.
 * This configures auth for ALL qlik-embed elements on the page.
 * autoRedirect: false prevents redirect to Qlik login page.
 */
function injectGlobalConfig() {
  if (configInjected) return
  if (document.querySelector('script[type="qlik-embed/config"]')) {
    configInjected = true
    return
  }

  const script = document.createElement("script")
  script.setAttribute("type", "qlik-embed/config")
  script.textContent = JSON.stringify({
    host: TENANT_URL,
    authType: "cookie",
    webIntegrationId: WEB_INTEGRATION_ID,
    autoRedirect: false,
  })
  document.head.appendChild(script)
  configInjected = true
}

export function QlikEmbed({ appId, sheetId }: QlikEmbedProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true

    async function init() {
      try {
        // 1. Get JWT token before rendering any Qlik component
        currentToken = await fetchToken()
        startTokenRefresh()

        if (!mounted || !containerRef.current) return

        // 2. Inject global config (once) — must come before import
        injectGlobalConfig()

        // 3. Load qlik-embed web components
        await import("@qlik/embed-web-components")

        if (!mounted || !containerRef.current) return

        // 4. Create qlik-embed element
        const embed = document.createElement("qlik-embed")
        embed.setAttribute("ui", "classic/app")
        embed.setAttribute("app-id", appId)
        if (sheetId) embed.setAttribute("sheet-id", sheetId)

        // getAccessToken must be an async function returning Promise<string>
        // This is how qlik-embed obtains the JWT for session creation
        const embedEl = embed as unknown as Record<string, unknown>
        embedEl.getAccessToken = async (): Promise<string> => {
          if (!currentToken) {
            currentToken = await fetchToken()
          }
          return currentToken
        }

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
