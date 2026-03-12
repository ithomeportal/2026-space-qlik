# Analytics Hub — Role-Based Qlik Dashboard Portal

> For detailed specs, see `docs/SPEC-*.md`

## Critical Rules

### Git & Commits
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Never commit secrets (.env, credentials, API keys)
- Push to GitHub directly; Vercel/Render auto-deploy from repo

### Server Actions & API Patterns
- All mutations via Next.js Server Actions (not API routes) except auth
- FastAPI backend handles: JWT generation for Qlik, report catalog CRUD, search index, usage analytics
- API response envelope: `{ success: boolean, data?: T, error?: string, meta?: { total, page, limit } }`
- Validate all inputs with Zod (frontend) and Pydantic (backend)

### Security (Non-Negotiable)
- NO hardcoded secrets — all via environment variables
- Qlik JWTs expire after 60 min, silent refresh before expiry
- Rate limiting: 300 req/min standard, 10 req/min for token generation
- CSP headers: only allow iframes from `mb01txe2h9rovgh.us.qlikcloud.com`
- CORS: restrict to Vercel deployment origin only
- Email auth codes: 8-digit, 10-min TTL, via Resend from `noreply@unilinkportal.com`

### Code Style
- Immutable updates only (spread operator, no mutation)
- Files < 400 lines (800 max), functions < 50 lines
- No `console.log` in production — use proper logging
- ONLY light mode — block dark mode from browser

### Qlik Embedding Rules
- Use `@qlik/embed-web-components` (`<qlik-embed>`) — NOT raw iframes
- Always `ui="classic/app"` with `auth-type="Jwt"`
- Single tenant: `mb01txe2h9rovgh.us.qlikcloud.com` (alias: `unilink.us.qlikcloud.com`)
- Mobile `(Mob)` app copies are excluded from the portal — only use production app IDs
- JWT IdP must be configured in Qlik Cloud before embedding works (see SPEC-QLIK.md)

---

## Feature Overview (1-liner each)

1. **Email Code Auth** — 8-digit code via Resend, NextAuth session, manual role management in admin
2. **Search-First Home** — Claude.ai-style centered search bar (cmdk), pinned reports, category grid
3. **Role-Based Catalog** — Users see only reports assigned to their role(s); roles managed in admin
4. **Report Cards** — Icon, title, category pill, description, owner, data freshness, favorite star
5. **Full-Page Embed** — `/reports/[id]` route with `<qlik-embed>` at 100% viewport, JWT auth
6. **Sidebar Drawer** — Quick-view 60%-width drawer from search results (Should Have)
7. **Smart Search** — Full-text via Typesense, filter chips (category, tags, freshness)
8. **Admin Console** — Report registry CRUD, role manager, usage analytics dashboard
9. **Favorites & Pinned** — Users pin reports to personal top row, stored in user_preferences
10. **Deep Links** — Stable URLs per embedded report, shareable, still role-gated
11. **AI Search (Phase 2)** — Semantic search via Anthropic embeddings + pgvector
12. **AI Summaries (Phase 2)** — Claude API generates plain-language report descriptions on hover
13. **Trending & Recent (Phase 2)** — Access log-based trending reports, recent history

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| Animation | Framer Motion |
| State | Zustand + React Query |
| Search UI | cmdk (Command Menu) |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js (email code via Resend) |
| Qlik Embed | `@qlik/embed-web-components` with JWT |
| Database | PostgreSQL (Aiven) |
| Search | Typesense (Phase 1) / pgvector (Phase 2) |
| Email | Resend |
| File Upload | UploadThing (if needed) |

---

## Key File Paths (Next.js App Router)

```
app/
  layout.tsx              # Root layout: providers, auth, header
  page.tsx                # Home: search bar + report grid
  reports/
    [id]/page.tsx         # Full-screen Qlik embed viewer
  admin/
    layout.tsx            # Admin guard + sidebar
    page.tsx              # Admin dashboard: usage stats
    reports/page.tsx      # Report catalog CRUD
    roles/page.tsx        # Role management
  api/
    auth/[...nextauth]/   # NextAuth handlers
    proxy/route.ts        # Backend proxy (avoids CORS from browser)
  (auth)/
    login/page.tsx        # Login page

components/
  SearchBar.tsx           # cmdk-based command palette
  ReportGrid.tsx          # CSS Grid + React Query, groups by category
  ReportCard.tsx          # Card with icon, title, pill, description, footer
  QuickPreview.tsx        # Radix Sheet drawer with Qlik embed at 50%
  QlikEmbed.tsx           # Wrapper for <qlik-embed> web component
  RoleGuard.tsx           # HOC checking session roles

lib/
  auth.ts                 # NextAuth config
  qlik.ts                 # Qlik token fetch + refresh logic
  api.ts                  # Backend API client (React Query)
```

---

## Environment Variables

### Frontend (Vercel)
```
NEXTAUTH_URL=https://<app>.vercel.app
NEXTAUTH_SECRET=<random-32-chars>
RESEND_API_KEY=<from-env>
BACKEND_URL=https://<backend>.onrender.com
NEXT_PUBLIC_QLIK_TENANT=mb01txe2h9rovgh.us.qlikcloud.com
```

### Backend (Render)
```
DATABASE_URL=postgres://avnadmin:<pass>@pg-111cab4b-unlkdata.b.aivencloud.com:10261/<db>?sslmode=require
QLIK_TENANT_URL=https://mb01txe2h9rovgh.us.qlikcloud.com
QLIK_PRIVATE_KEY=<RSA private key for JWT signing>
QLIK_ISSUER=<JWT IdP issuer from Qlik Cloud>
QLIK_KEY_ID=<JWT IdP key ID from Qlik Cloud>
RESEND_API_KEY=<from-env>
TYPESENSE_API_KEY=<generated>
TYPESENSE_HOST=<typesense-instance>
```

---

## Role Access Summary

### Portal Roles (managed in admin console)
| Role | Can See | Can Do |
|------|---------|--------|
| **Admin** | All reports + admin console | CRUD reports, manage roles, view usage |
| **Executive** | All reports across divisions | View + favorite + search |
| **Finance** | Finance + Budget reports | View + favorite + search |
| **Operations** | Ops + Carrier + Scorecard reports | View + favorite + search |
| **Sales** | Sales + Attrition + Awards reports | View + favorite + search |
| **HR** | HR reports only | View + favorite + search |
| **IT** | IT + VoIP + Managed Services | View + favorite + search |
| **DFW** | DFW-specific reports | View + favorite + search |
| **CORP** | CORP-specific reports | View + favorite + search |

### User Source
- Seed from time-off DB (121 active employees): email, name, department, jobTitle, company
- Auth via email code (Resend) — only `@unilinktransportation.com` emails
- Roles assigned manually by admin in the portal

---

## Qlik Tenant Summary

- **Tenant**: `mb01txe2h9rovgh.us.qlikcloud.com`
- **Tenant ID**: `ZC6dict00GLAZhISVRVWKm4d-l105j0n`
- **API Key**: `bot-mcp` (expires 2027-03-12) — stored in `/BOT/qlik-api/.env`
- **JWT IdP**: NOT YET CONFIGURED — must be set up before embedding works
- **20 production apps** across 7 spaces (see SPEC-QLIK-INVENTORY.md)
- **10 mobile copies** in Mobile space — excluded from portal

---

## Spec Files Reference

| File | Contents |
|------|----------|
| `docs/SPEC-AUTH.md` | Auth flow, email code, NextAuth config, role management, user seeding |
| `docs/SPEC-UI.md` | Design system, colors, typography, grid, spacing, motion, components |
| `docs/SPEC-QLIK.md` | Qlik embed integration, JWT flow, IdP setup, web component usage |
| `docs/SPEC-QLIK-INVENTORY.md` | Full app inventory with IDs, sheets, spaces, categories |
| `docs/SPEC-DATA.md` | PostgreSQL schema, API endpoints, Typesense index |
| `docs/SPEC-SEARCH.md` | Search engine, AI semantic search, Typesense, pgvector, cmdk |
| `docs/SPEC-ROADMAP.md` | Phased delivery plan, success metrics, lessons learned |
