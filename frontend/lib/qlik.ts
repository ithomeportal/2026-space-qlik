let cachedToken: string | null = null
let tokenExpiresAt = 0

export async function getQlikToken(): Promise<string> {
  const now = Date.now()

  // Return cached if still valid (10 min buffer)
  if (cachedToken && tokenExpiresAt - now > 10 * 60 * 1000) {
    return cachedToken
  }

  const res = await fetch("/api/proxy/qlik/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })

  if (!res.ok) {
    throw new Error("Failed to fetch Qlik token")
  }

  const json = await res.json()
  cachedToken = json.data.token
  tokenExpiresAt = now + 50 * 60 * 1000

  return cachedToken!
}

// Start token refresh interval
let refreshInterval: ReturnType<typeof setInterval> | null = null

export function startTokenRefresh() {
  if (refreshInterval) return
  refreshInterval = setInterval(
    () => {
      getQlikToken().catch(() => {
        /* silently retry next interval */
      })
    },
    50 * 60 * 1000,
  )
}

export function stopTokenRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}
