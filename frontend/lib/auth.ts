import { PrismaAdapter } from "@auth/prisma-adapter"
import NextAuth from "next-auth"
import EmailProvider from "next-auth/providers/email"
import { Resend } from "resend"

import { prisma } from "./db"

const resend = new Resend(process.env.RESEND_API_KEY || "re_placeholder")

function generateCode(token: string): string {
  // Generate a deterministic 8-digit code from the token
  let hash = 0
  for (let i = 0; i < token.length; i++) {
    const char = token.charCodeAt(i)
    hash = ((hash << 5) - hash + char) | 0
  }
  return String(Math.abs(hash) % 100000000).padStart(8, "0")
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  adapter: PrismaAdapter(prisma),
  providers: [
    EmailProvider({
      server: {},
      from: "noreply@unilinkportal.com",
      sendVerificationRequest: async ({ identifier: email, token }) => {
        const code = generateCode(token)
        await resend.emails.send({
          from: "Analytics Hub <noreply@unilinkportal.com>",
          to: email,
          subject: `Your login code: ${code}`,
          html: `
            <div style="font-family: Inter, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
              <h2 style="color: #1B3A5C; margin-bottom: 24px;">Analytics Hub</h2>
              <p style="color: #111827; font-size: 16px;">Your verification code is:</p>
              <p style="font-size: 32px; font-weight: 700; color: #2563EB; letter-spacing: 4px; margin: 24px 0;">${code}</p>
              <p style="color: #6B7280; font-size: 14px;">This code expires in 10 minutes.</p>
            </div>
          `,
        })
      },
      maxAge: 10 * 60,
    }),
  ],
  callbacks: {
    async signIn({ user }) {
      return user.email?.endsWith("@unilinktransportation.com") ?? false
    },
    async session({ session, token }) {
      if (token.sub) {
        session.user.id = token.sub

        const dbUser = await prisma.user.findUnique({
          where: { id: token.sub },
          include: {
            userRoles: {
              include: { role: true },
            },
          },
        })

        if (dbUser) {
          session.user.roles = dbUser.userRoles.map((ur: { role: { name: string } }) => ur.role.name)
          session.user.department = dbUser.department
          session.user.company = dbUser.company
        }
      }
      return session
    },
    async jwt({ token, user }) {
      if (user) {
        token.sub = user.id
      }
      return token
    },
  },
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
    verifyRequest: "/login/verify",
  },
})
