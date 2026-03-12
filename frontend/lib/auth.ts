import { PrismaAdapter } from "@auth/prisma-adapter"
import NextAuth from "next-auth"
import Resend from "next-auth/providers/resend"

import { prisma } from "./db"

function generateCode(token: string): string {
  let hash = 0
  for (let i = 0; i < token.length; i++) {
    const char = token.charCodeAt(i)
    hash = ((hash << 5) - hash + char) | 0
  }
  return String(Math.abs(hash) % 100000000).padStart(8, "0")
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  adapter: PrismaAdapter(prisma),
  debug: process.env.NODE_ENV === "development",
  providers: [
    Resend({
      apiKey: process.env.RESEND_API_KEY,
      from: "Analytics Hub <noreply@unilinkportal.com>",
      sendVerificationRequest: async ({ identifier: email, token, url }) => {
        const code = generateCode(token)
        const { Resend: ResendClient } = await import("resend")
        const resend = new ResendClient(process.env.RESEND_API_KEY)
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
              <p style="color: #6B7280; font-size: 14px; margin-top: 24px;">Or <a href="${url}" style="color: #2563EB;">click here to sign in directly</a>.</p>
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

        try {
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
        } catch (e) {
          console.error("Failed to fetch user roles:", e)
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
