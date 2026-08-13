import { DefaultSession } from "next-auth"

declare module "next-auth" {
  interface Session {
    user: {
      id: string
      roles: string[]
      department: string | null
      company: string | null
    } & DefaultSession["user"]
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    sub: string
    // Roles + org fields are cached in the token so a session read needs no
    // database and no backend call (see ROLES_TTL_MS in lib/auth.ts).
    roles?: string[]
    department?: string | null
    company?: string | null
    /** epoch ms when `roles` was last refreshed */
    rolesAt?: number
  }
}
