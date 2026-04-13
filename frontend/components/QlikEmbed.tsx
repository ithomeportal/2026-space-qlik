"use client"

import { useEffect, useRef, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"

interface QlikEmbedProps {
  appId: string
  sheetId?: string | null
  useClassic?: boolean
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
let sessionPromise: Promise<void> | null = null

async function establishQlikSession(): Promise<void> {
  // Use a Promise singleton to prevent race conditions when multiple
  // QlikEmbed components mount simultaneously
  if (sessionPromise) return sessionPromise

  sessionPromise = _doEstablishSession()
  try {
    await sessionPromise
  } catch {
    // Reset so next attempt can retry
    sessionPromise = null
    throw new Error("Qlik session establishment failed")
  }
}

async function _doEstablishSession(): Promise<void> {
  // 1. Get a JWT for the universal portal viewer
  currentToken = await fetchViewerToken()

  // 2. Exchange the JWT for a Qlik session cookie with retry
  const maxRetries = 2
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
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
        return // Session established successfully
      }
      console.warn(
        `[QlikEmbed] Session exchange returned ${resp.status} (attempt ${attempt + 1}/${maxRetries + 1}) — verify Web Integration allowed origins include ${window.location.origin}`
      )
    } catch (err) {
      console.warn(
        `[QlikEmbed] Session exchange failed (attempt ${attempt + 1}/${maxRetries + 1})`,
        err
      )
    }
    // Wait before retry (1s, then 2s)
    if (attempt < maxRetries) {
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)))
    }
  }
  // All retries failed — component will still render with getAccessToken fallback
  console.warn("[QlikEmbed] All session exchange attempts failed — falling back to getAccessToken")
}

export function QlikEmbed({ appId, sheetId, useClassic }: QlikEmbedProps) {
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

        if (useClassic || !sheetId) {
          // Use classic/app for reports with Dashboard Bundle objects
          // (e.g. qlik-date-picker) that are unsupported in analytics/sheet
          embed.setAttribute("ui", "classic/app")
          if (sheetId) {
            embed.setAttribute("sheet-id", sheetId)
          }
        } else {
          embed.setAttribute("ui", "analytics/sheet")
          embed.setAttribute("sheet-id", sheetId)
        }

        embed.setAttribute("app-id", appId)
        embed.setAttribute("host", TENANT_URL)
        embed.setAttribute("auth-type", "cookie")
        embed.setAttribute("web-integration-id", WEB_INTEGRATION_ID)
        embed.setAttribute("toolbar", "false")

        // Provide getAccessToken as fallback — if the session cookie
        // was blocked, qlik-embed's service worker will use this JWT.
        // Always fetch a fresh token to handle cases where the initial
        // session exchange failed due to backend cold start.
        const embedEl = embed as unknown as Record<string, unknown>
        embedEl.getAccessToken = async (): Promise<string> => {
          try {
            currentToken = await fetchViewerToken()
          } catch {
            if (currentToken) return currentToken
            throw new Error("Failed to fetch Qlik access token")
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
  }, [appId, sheetId, useClassic])

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
