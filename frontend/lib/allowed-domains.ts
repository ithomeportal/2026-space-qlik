/**
 * Company email domains — who may sign in, and who this app may email.
 *
 * These are the Microsoft 365 tenant's *verified* domains (Graph `GET /domains`).
 *
 * The previous rule was a single hardcoded suffix check for
 * `@unilinktransportation.com`, which meant staff on `oiltex.com`,
 * `mencarllc.com`, `unilinkportal.com` and the other eleven tenant domains could
 * not log in at all. Widening to the full verified list fixes that and matches
 * the backend guard in `backend/app/services/allowed_domains.py`.
 *
 * Auth.js checks `signIn` BEFORE generating and mailing the magic-link token, so
 * this doubles as the send guard for the login email.
 *
 * Override with NEXT_PUBLIC-free `ALLOWED_EMAIL_DOMAINS` (comma-separated) when
 * the tenant adds a domain; updating this list is the durable fix.
 */

export const ORG_EMAIL_DOMAINS: readonly string[] = [
  "hireinternational.com",
  "itunilink.com",
  "mencarllc.com",
  "mencarotr.com",
  "mspekt.com",
  "oiltex.com",
  "otxtransport.com",
  "otxtransportation.com",
  "prosperityenergyresources.com",
  "seekequipment.com",
  "u-capital.com",
  "unilinkcapital.com",
  "unilinkportal.com",
  "unilinktransportation.com",
  "unilinktransportationsa.mail.onmicrosoft.com",
  "unilinktransportationsa.onmicrosoft.com",
]

function resolveDomains(): string[] {
  const override = process.env.ALLOWED_EMAIL_DOMAINS
  if (override && override.trim()) {
    return override
      .split(",")
      .map((d) => d.trim().toLowerCase().replace(/^@/, ""))
      .filter(Boolean)
  }
  return [...ORG_EMAIL_DOMAINS]
}

/** True when `value` is an address on a domain the organization owns. */
export function isOrgEmail(value: string | null | undefined): boolean {
  if (!value) return false
  const at = value.lastIndexOf("@")
  if (at < 1 || at === value.length - 1) return false
  return resolveDomains().includes(value.slice(at + 1).trim().toLowerCase())
}
