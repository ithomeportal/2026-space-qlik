# SPEC-AUTH: Authentication & Role Management

## 1. Auth Flow — Email Code (NOT SSO)

Users authenticate via an 8-digit numeric code sent to their corporate email.

### Flow:
1. User enters email on `/login`
2. Frontend calls NextAuth `signIn("email", { email })`
3. NextAuth generates 8-digit code, stores hash in DB
4. Resend sends code from `noreply@unilinkportal.com`
5. User enters code on verification page
6. NextAuth validates, creates session (JWT-based, not database sessions)
7. Session includes: userId, email, name, roles[], department, company

### Constraints:
- Only `@unilinktransportation.com` emails accepted
- Code expires after 10 minutes
- Max 3 failed attempts per email per 15 minutes
- Resend API key: `<from-env>` (stored in `.env` only)
- Always from: `noreply@unilinkportal.com`

### NextAuth Configuration:
```typescript
// lib/auth.ts
import NextAuth from "next-auth"
import EmailProvider from "next-auth/providers/email"
import { Resend } from "resend"

const resend = new Resend(process.env.RESEND_API_KEY)

export const authOptions = {
  providers: [
    EmailProvider({
      server: {}, // Not used — custom sendVerificationRequest
      from: "noreply@unilinkportal.com",
      sendVerificationRequest: async ({ identifier: email, token }) => {
        // Generate 8-digit code from token
        const code = generateCode(token)
        await resend.emails.send({
          from: "Analytics Hub <noreply@unilinkportal.com>",
          to: email,
          subject: `Your login code: ${code}`,
          html: `<p>Your verification code is: <strong>${code}</strong></p>`
        })
      },
      maxAge: 10 * 60, // 10 minutes
    })
  ],
  callbacks: {
    async signIn({ user }) {
      // Only allow corporate emails
      return user.email?.endsWith("@unilinktransportation.com") ?? false
    },
    async session({ session, token }) {
      // Enrich session with roles from DB
      const dbUser = await getUserWithRoles(token.sub)
      session.user.roles = dbUser.roles
      session.user.department = dbUser.department
      session.user.company = dbUser.company
      return session
    },
    async jwt({ token, user }) {
      if (user) token.sub = user.id
      return token
    }
  },
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
    verifyRequest: "/login/verify",
  }
}
```

---

## 2. Role Management

Roles are managed **manually in the admin console** — no Azure AD / SSO group sync.

### Role Model:
- A user can have **multiple roles** (many-to-many: `user_roles` table)
- Roles map to sets of reports (many-to-many: `role_report_access` table)
- A user sees the **union** of all reports their roles grant access to
- Admin role sees everything + the admin console

### Default Roles:
| Role | Reports Visible |
|------|----------------|
| admin | All + admin console |
| executive | All reports (read-only) |
| finance | Budget Follow-up, Budget - Sales |
| operations | Customer Scorecard, Carrier Savings, Available, Customer Attrition, Spot Details, RFP Tracker |
| sales | Attrition to Sales, Attrition Week-Over-Week, Awards Tracker, Budget - Sales |
| hr | HR - IT Report, HR - Access Log Doors |
| it | Vonage VoIP, IT Managed Services, HR - Access Log Doors |
| dfw | DFW Executive Report, DFW X-RAY, Executive Report, DIRECT COMPARE |
| corp | CORP X-RAY, Executive Report, DIRECT COMPARE |

### Admin Console — Role Manager:
- Create/edit/delete roles
- Assign users to roles (search by name/email)
- Assign reports to roles (checkboxes)
- Preview: "Show me what user X would see"
- Bulk import from CSV (email, role pairs)

---

## 3. User Seeding

Initial user list comes from the **time-off system** database.

### Source:
- Database: Aiven PostgreSQL (same cluster, `timeoff_at_unilink_portal` DB)
- Table: `users`
- Key fields: `email`, `name` (`firstName` + `lastName`), `department`, `jobTitle`, `companyName`, `isActive`, `role`, `roleLevel`

### Seeding Script Logic:
1. Connect to time-off DB, SELECT active employees
2. For each employee, create a user record in the analytics hub DB
3. Auto-assign portal roles based on department mapping:
   - department contains "Sales" → `sales` role
   - department contains "Finance" / "Accounting" → `finance` role
   - department contains "HR" / "Human" → `hr` role
   - department contains "IT" / "Tech" → `it` role
   - department contains "Operations" / "Ops" → `operations` role
   - `roleLevel` = "OWNER" or "DIRECTOR" → additionally `executive` role
4. Admin role assigned manually after seeding

### Stats:
- 121 active employees
- 91 US + 30 Mexico
- 3 companies: Unilink Transportation, Oiltex, Seek Equipment
