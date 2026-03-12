# UNILINK Space (Analytics Hub) — Role-Based Qlik Dashboard Portal

> For detailed specs, see `docs/SPEC-*.md`

## Critical Rules

### Git & Docs
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Never commit secrets (.env, credentials, API keys)
- Never commit docs/ — all documentation is local-only (.gitignore excludes docs/)
- Push to GitHub directly; Vercel/Render auto-deploy from repo
- No author/co-author names in commits or LICENSE

### Server Actions & API Patterns
- All mutations via Next.js Server Actions (not API routes) except auth
- FastAPI backend: JWT generation, report catalog CRUD, search index, usage analytics
- API envelope: `{ success: boolean, data?: T, error?: string, meta?: { total, page, limit } }`
- Validate inputs with Zod (frontend) and Pydantic (backend)

### Security (Non-Negotiable)
- NO hardcoded secrets — all via environment variables
- Qlik JWTs: 60-min expiry, silent refresh before expiry
- Rate limiting: 300 req/min standard, 10 req/min for token generation
- CSP: only allow iframes from `mb01txe2h9rovgh.us.qlikcloud.com`
- CORS: restrict to Vercel deployment origin only
- Email auth: 8-digit code, 10-min TTL, via Resend (provider ID: "resend", NOT "email")

### Code Style
- Immutable updates only (spread operator, no mutation)
- Files < 400 lines (800 max), functions < 50 lines
- No `console.log` in production
- ONLY light mode — block dark mode

### Qlik Embedding
- Use `@qlik/embed-web-components` (`<qlik-embed>`) — NOT raw iframes
- Always `ui="classic/app"` with `auth-type="Jwt"`
- Tenant: `mb01txe2h9rovgh.us.qlikcloud.com`
- Mobile `(Mob)` app copies excluded — only production app IDs
- JWT IdP: configured (issuer: `https://analytics-hub.unilinkportal.com`, key: `analytics-hub-key-1`)

---

## Features

1. **Email Code Auth** — 8-digit code via Resend, NextAuth session, admin role management
2. **Search-First Home** — Centered search bar (cmdk), pinned reports, category grid
3. **Role-Based Catalog** — Users see only reports assigned to their role(s)
4. **Report Cards** — Icon, title, category pill, description, owner, freshness, favorite star
5. **Full-Page Embed** — `/reports/[id]` with `<qlik-embed>` at 100vh, JWT auth
6. **Smart Search** — Full-text via Typesense, filter chips (category, tags)
7. **Admin Console** — Report CRUD, role manager, usage analytics
8. **Favorites & Pinned** — Personal pinned row in user_preferences
9. **Deep Links** — Stable URLs per report, shareable, role-gated

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| State | Zustand + React Query |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js v5 beta-30 (Resend provider, JWT strategy) |
| Qlik Embed | `@qlik/embed-web-components` with JWT |
| Database | PostgreSQL (Aiven) |
| Search | Typesense |
| Email | Resend |

---

## Key File Paths

```
frontend/
  app/
    layout.tsx              # Root layout: providers, auth, header
    page.tsx                # Home: search bar + report grid
    reports/[id]/page.tsx   # Full-screen Qlik embed viewer
    admin/                  # Admin guard + sidebar + CRUD pages
    api/auth/[...nextauth]/ # NextAuth handlers
    api/proxy/[...path]/    # Backend proxy
    (auth)/login/page.tsx   # Login page
  components/
    SearchBar.tsx           # cmdk command palette
    ReportGrid.tsx          # CSS Grid, groups by category
    ReportCard.tsx          # Card component
    QlikEmbed.tsx           # <qlik-embed> wrapper
    RoleGuard.tsx           # Session role check
  lib/
    auth.ts                 # NextAuth config
    qlik.ts                 # Token fetch + refresh
    api.ts                  # React Query hooks

backend/
  app/
    main.py                 # FastAPI app, CORS, health check
    config.py               # Pydantic Settings
    routers/
      reports.py            # GET /api/reports (role-filtered)
      qlik.py               # POST /api/qlik/token (RS256 JWT)
      search.py             # GET /api/reports/search
      preferences.py        # GET/PATCH /api/user/preferences
      admin.py              # Admin CRUD endpoints
    services/
      seed.py               # DB seeding script
```

---

## Environment Variables

### Frontend (Vercel) — project: `2026-space-qlik-front`
```
AUTH_URL=https://test.unilink.space
AUTH_SECRET=<from-env>
AUTH_TRUST_HOST=true
NEXTAUTH_URL=https://test.unilink.space
NEXTAUTH_SECRET=<from-env>
DATABASE_URL=<from-env> (must start with postgresql://)
RESEND_API_KEY=<from-env>
BACKEND_URL=https://two026-space-qlik-back.onrender.com
NEXT_PUBLIC_QLIK_TENANT=mb01txe2h9rovgh.us.qlikcloud.com
```

### Backend (Render)
```
DATABASE_URL=<from-env>
QLIK_TENANT_URL=https://mb01txe2h9rovgh.us.qlikcloud.com
QLIK_PRIVATE_KEY=<from-env>
QLIK_ISSUER=https://analytics-hub.unilinkportal.com
QLIK_KEY_ID=analytics-hub-key-1
ALLOWED_ORIGINS=https://test.unilink.space,https://2026-space-qlik-front.vercel.app
```

---

## Role Access

| Role | Reports |
|------|---------|
| Admin | All + admin console |
| Executive | All reports |
| Finance | Finance + Budget |
| Operations | Ops + Carrier + Scorecard |
| Sales | Sales + Attrition + Awards |
| HR | HR reports |
| IT | IT + VoIP + Managed Services |
| DFW | DFW-specific |
| CORP | CORP-specific |

Users seeded from time-off DB. Auth: `@unilinktransportation.com` only. Roles assigned by admin.

---

## Qlik Tenant

- **Tenant**: `mb01txe2h9rovgh.us.qlikcloud.com`
- **Tenant ID**: `ZC6dict00GLAZhISVRVWKm4d-l105j0n`
- **API Key**: `bot-mcp` (expires 2027-03-12) — in `/BOT/qlik-api/.env`
- **JWT IdP**: Configured (ID: `69b30b03dbb54989a11adb6b`)
- **20 production apps** across 7 spaces (see local docs/SPEC-QLIK-INVENTORY.md)

---

## Deployments

| Service | URL |
|---------|-----|
| Frontend | https://test.unilink.space (also: 2026-space-qlik-front.vercel.app) |
| Backend | https://two026-space-qlik-back.onrender.com |
| Database | Aiven PostgreSQL (`analytics_hub`) |
| Repo | https://github.com/ithomeportal/2026-space-qlik |

---

## Spec Files (local only, not in git)

| File | Contents |
|------|----------|
| `docs/SPEC-AUTH.md` | Auth flow, email code, NextAuth, roles, user seeding |
| `docs/SPEC-UI.md` | Design system, colors, typography, components |
| `docs/SPEC-QLIK.md` | Qlik embed, JWT flow, IdP setup |
| `docs/SPEC-QLIK-INVENTORY.md` | Full app inventory with IDs, sheets, categories |
| `docs/SPEC-DATA.md` | PostgreSQL schema, API endpoints, Typesense index |
| `docs/SPEC-SEARCH.md` | Search engine, Typesense, cmdk |
| `docs/SPEC-ROADMAP.md` | Phased delivery, success metrics, lessons learned |
