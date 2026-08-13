import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"

import { fetchUserContext, verifyLoginCode } from "./auth-backend"
import { isOrgEmail } from "./allowed-domains"

// The 8-digit email code is now verified by the FastAPI backend, not by Prisma
// in this process. See lib/auth-backend.ts for why (Aiven ip_filter: the
// frontend must stop reaching Postgres so Vercel's rotating egress IPs stop
// being part of the allowlist problem).
//
// What this replaced: `PrismaAdapter` + the Resend magic-link provider. The
// adapter was load-bearing for `verification_tokens`, `users` and `accounts`, so
// the alternative was reimplementing ~8 adapter methods over HTTP with exact
// date/null semantics. Since the product's actual login IS the 8-digit code
// (the magic link was a secondary affordance in the mail), a Credentials
// provider expresses the same flow with far less contract surface — and
// Credentials + JWT needs no adapter at all.
//
// The emailed "click here to sign in directly" link is preserved: the backend
// points it at /login/verify?email=…&code=…, which auto-submits. Same exposure
// class as the old magic link, which also carried a usable secret in the URL.
//
// ⚠ Session strategy MUST stay "jwt". A database session strategy requires an
// adapter, which is the thing being removed.

// How long the roles baked into the JWT are trusted before a refresh is
// attempted. The old `session()` callback hit Postgres on EVERY session read;
// doing that against this backend would put a Render cold start (30-60s) in
// front of every page load. Caching in the token and refreshing on an interval
// is both faster and more robust — a backend outage now degrades to slightly
// stale roles instead of no roles — at the cost of a role change taking up to
// this long to appear. Admin role edits are not time-critical.
const ROLES_TTL_MS = 5 * 60 * 1000

export const { handlers, signIn, signOut, auth } = NextAuth({
  debug: process.env.NODE_ENV === "development",
  providers: [
    Credentials({
      id: "email-code",
      name: "Email code",
      credentials: {
        email: { label: "Email", type: "email" },
        code: { label: "Code", type: "text" },
      },
      async authorize(credentials) {
        const email = String(credentials?.email ?? "").trim().toLowerCase()
        const code = String(credentials?.code ?? "").trim()

        // Cheap local rejects before spending a backend round-trip. The backend
        // re-checks both — this is a shortcut, not the authority.
        if (!email || !/^\d{8}$/.test(code)) return null
        if (!isOrgEmail(email)) {
          console.warn("[auth] sign-in rejected for non-tenant domain")
          return null
        }

        const res = await verifyLoginCode(email, code)
        if (!res.ok) {
          // Returning null renders as "invalid code" to the user. Distinguish
          // the causes in the log so a backend outage is not misread as a flood
          // of bad codes.
          console.warn(`[auth] code verification failed (status ${res.status})`)
          return null
        }

        const u = res.data.user
        return {
          id: u.id,
          email: u.email,
          name: u.name,
          // Carried into the JWT below.
          roles: u.roles,
          department: u.department,
          company: u.company,
        } as never
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      // Fresh sign-in: seed everything from what authorize() returned.
      if (user) {
        const u = user as unknown as {
          id: string
          roles?: string[]
          department?: string | null
          company?: string | null
        }
        token.sub = u.id
        token.roles = u.roles ?? []
        token.department = u.department ?? null
        token.company = u.company ?? null
        token.rolesAt = Date.now()
        return token
      }

      // Subsequent reads: refresh roles once the cached copy is stale. On any
      // failure keep what we have — never sign the user out or blank their roles
      // because the backend was cold.
      const rolesAt = typeof token.rolesAt === "number" ? token.rolesAt : 0
      if (token.sub && Date.now() - rolesAt > ROLES_TTL_MS) {
        const res = await fetchUserContext(token.sub)
        if (res.ok && res.data) {
          token.roles = res.data.roles
          token.department = res.data.department
          token.company = res.data.company
          token.rolesAt = Date.now()
        } else {
          // Back off so a hard-down backend is not re-hit on every single
          // request; the stale roles stay usable meanwhile.
          token.rolesAt = Date.now() - ROLES_TTL_MS + 30_000
        }
      }
      return token
    },
    async session({ session, token }) {
      // Reads the token only — no network, no database. This is what makes page
      // loads independent of the backend being warm.
      if (token.sub) {
        session.user.id = token.sub
        session.user.roles = (token.roles as string[] | undefined) ?? []
        session.user.department = (token.department as string | null | undefined) ?? null
        session.user.company = (token.company as string | null | undefined) ?? null
      }
      return session
    },
  },
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
})
