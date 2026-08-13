// ⚠ UNUSED as of 2026-08-12 (`c6d4f77`) — nothing in this app imports `prisma`
// any more. Login codes are issued and verified by the FastAPI backend, and the
// frontend deliberately does NOT connect to Postgres: Vercel's ~23 rotating AWS
// egress IPs were the sole blocker to removing Aiven's `ip_filter: 0.0.0.0/0`
// from an instance holding 27 databases.
//
// Kept on disk ONLY so the auth change can be rolled back with a plain
// `git revert`. Delete this file, `prisma/`, the `@prisma/client` dependency and
// the `postinstall: prisma generate` script together, once a human has confirmed
// a real login works — then drop `DATABASE_URL` from Vercel. See
// docs/SPEC-AUTH.md §1 and /BOT/aiven-mcp/docs/SPEC-security.md.
//
// Do NOT re-import this to "just query one thing" — that would silently put
// Vercel back in the allowlist problem.
import { PrismaClient } from "@prisma/client"

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
}

export const prisma = globalForPrisma.prisma ?? new PrismaClient()

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma
