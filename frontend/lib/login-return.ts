// Where a signed-out reader goes after login, so a report link in an e-mail still
// lands on that report. The value travels in a URL anyone can craft: read it only
// through safeReturnPath, which keeps every redirect on this site. The backend's
// safe_return_path (routers/auth_email.py) applies the same rules; one test table
// (backend/tests/test_login_return_path.py) drives both.

const RETURN_PARAM = "callbackUrl"
const MAX_LENGTH = 1000
const HOME = "/"

// Login would loop back to itself; an API route is not a page to land on.
const NOT_A_DESTINATION = /^\/(login|api)(?:[/?#]|$)/
// A browser reads "\" as "/" and drops tabs and newlines, so "/\evil.com" and
// "/<tab>/evil.com" both mean another site.
const UNSAFE_CHARACTERS = /[\\\u0000-\u001f\u007f]/
// A browser resolves "/x/../api" to "/api" before loading it, so a dot segment in
// the path could reach what NOT_A_DESTINATION refuses. No page link needs one.
const DOT_SEGMENT = /(^|\/)(\.|%2e){1,2}(\/|$)/i

/** The path if it is a page on this site, otherwise home. */
export function safeReturnPath(raw: unknown): string {
  if (typeof raw !== "string" || raw.length > MAX_LENGTH) return HOME
  if (!raw.startsWith("/") || raw.startsWith("//")) return HOME
  if (UNSAFE_CHARACTERS.test(raw) || NOT_A_DESTINATION.test(raw)) return HOME
  if (DOT_SEGMENT.test(raw.split(/[?#]/, 1)[0])) return HOME
  return raw
}

/** Adds the destination to a login URL. Home is the default, so it adds nothing. */
export function withReturnPath(url: string, returnPath: string): string {
  if (returnPath === HOME) return url
  const separator = url.includes("?") ? "&" : "?"
  return `${url}${separator}${RETURN_PARAM}=${encodeURIComponent(returnPath)}`
}

/** The login URL that brings the reader back to the page they are on now. */
export function loginUrlForCurrentPage(): string {
  if (typeof window === "undefined") return "/login"
  const { pathname, search } = window.location
  return withReturnPath("/login", safeReturnPath(`${pathname}${search}`))
}

/** The validated destination carried by the current URL. */
export function returnPathFromLocation(): string {
  if (typeof window === "undefined") return HOME
  return safeReturnPath(new URLSearchParams(window.location.search).get(RETURN_PARAM))
}
