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

async function fetchViewerToken(): Promise<string> {
  const res = await fetch("/api/proxy/qlik/viewer-token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error("Failed to fetch Qlik token")
  const json = await res.json()
  return json.data.token
}

let currentToken: string | null = null
let sessionEstablished = false

async function establishQlikSession(): Promise<void> {
  if (sessionEstablished) return

  // 1. Get a JWT for the universal portal viewer (now includes nbf claim)
  currentToken = await fetchViewerToken()

  // 2. Exchange the JWT for a Qlik session cookie
  // This call goes to Qlik Cloud directly — the browser stores the session cookie.
  // The JWT now includes the required `nbf` claim that was previously missing,
  // which caused a silent 400 error and the AUTHORIZE button fallback.
  try {
    const resp = await fetch(
      `${TENANT_URL}/login/jwt-session?qlik-web-integration-id=${WEB_INTEGRATION_ID}`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Authorization": `Bearer ${currentToken}`,
          "qlik-web-integration-id": WEB_INTEGRATION_ID,
        },
      }
    )
    if (resp.ok) {
      sessionEstablished = true
    }
  } catch {
    // If the direct exchange fails (CORS or cookie blocking),
    // fall back to getAccessToken approach below
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
        // 1. Establish Qlik session (JWT→cookie exchange)
        await establishQlikSession()

        if (!mounted || !containerRef.current) return

        // 2. Load qlik-embed web components
        await import("@qlik/embed-web-components")

        if (!mounted || !containerRef.current) return

        // 3. Create qlik-embed element — viewer-only mode
        const embed = document.createElement("qlik-embed")

        if (sheetId) {
          embed.setAttribute("ui", "analytics/sheet")
          embed.setAttribute("sheet-id", sheetId)
        } else {
          embed.setAttribute("ui", "classic/app")
        }

        embed.setAttribute("app-id", appId)
        embed.setAttribute("host", TENANT_URL)
        embed.setAttribute("auth-type", "cookie")
        embed.setAttribute("web-integration-id", WEB_INTEGRATION_ID)
        embed.setAttribute("toolbar", "false")

        // Provide getAccessToken as fallback — if the session cookie
        // was blocked, qlik-embed's service worker will use this JWT
        const embedEl = embed as unknown as Record<string, unknown>
        embedEl.getAccessToken = async (): Promise<string> => {
          if (!currentToken) {
            currentToken = await fetchViewerToken()
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
