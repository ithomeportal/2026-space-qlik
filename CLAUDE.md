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
- Next.js proxy sends user info as JSON in Authorization header (NOT a JWT) — backend parses with `json.loads`

### Security (Non-Negotiable)
- NO hardcoded secrets — all via environment variables
- Qlik JWTs: 60-min expiry, silent refresh before expiry
- Rate limiting: 300 req/min standard, 10 req/min for token generation
- CSP: allow `mb01txe2h9rovgh.us.qlikcloud.com` + `cdn.qlikcloud.com` (scripts, styles, connect, worker, frame)
- CORS: restrict to Vercel deployment origin only
- Email auth: 8-digit code, 10-min TTL, via Resend (provider ID: "resend", NOT "email")

### Vercel Env Var Management (Critical)
- ALWAYS run `vercel env` commands from `frontend/` directory (correct `.vercel/project.json`)
- Use `printf 'value' | npx vercel env add NAME production` — NOT `echo` (adds newline)
- Never run `vercel --prod` from repo root — use git push for auto-deploy
- After changing env vars, push empty commit to trigger redeploy with new values

### NextAuth v5 Gotchas
- Provider ID is `"resend"` not `"email"` — affects signIn() and callback URLs
- Requires `AUTH_SECRET` (not just `NEXTAUTH_SECRET`) + `AUTH_TRUST_HOST=true`
- Tokens are hashed before DB storage — code verification uses `email_codes` table, NOT `verification_tokens`
- Login page must check session and redirect authenticated users to `/`

### Code Style
- Immutable updates only (spread operator, no mutation)
- Files < 400 lines (800 max), functions < 50 lines
- No `console.log` in production
- ONLY light mode — block dark mode

### Qlik Embedding
- Use `@qlik/embed-web-components` npm package with `auth-type="cookie"` — NOT `auth-type="jwt"` (invalid)
- Valid auth-type values: `apikey`, `cookie`, `none`, `noauth`, `oauth2`, `anonymous`, `windowscookie`, `reference`
- Set `getAccessToken` as an async JS property on the element (returns Promise<string> with JWT)
- There is NO `configure()` method — all config goes as attributes on each `<qlik-embed>` element
- Must include `host`, `auth-type`, `web-integration-id` attributes on every element
- Viewer-only: use `ui="analytics/sheet"` + `toolbar="false"` + specific `sheet-id`
- `ui="classic/app"` = full app with sheet tabs/editing; `ui="analytics/sheet"` = single sheet, modern responsive
- Must include `web-integration-id` attribute — Qlik rejects origins not in the web integration
- JWT `groups` claim always includes "Viewers" — this group must have "Can view" role on Qlik spaces
- Web Integration ID: `UcOYHRHZf7W4ydusUB3cJPin3HHOPnit` (allowed origins: test/www/app/analytics.unilink.space, Vercel, localhost)
- Always `ui="classic/app"` for full app embeds
- Tenant: `mb01txe2h9rovgh.us.qlikcloud.com`
- Mobile `(Mob)` app copies excluded — only production app IDs
- JWT IdP: configured (issuer: `https://analytics-hub.unilinkportal.com`, key: `analytics-hub-key-1`)

### Database Seeding
- Seed uses `ON CONFLICT (qlik_app_id) DO UPDATE` — idempotent, no duplicates
- Never use `dict.pop()` on module-level constants — use `dict.get()` to avoid mutation across calls
- Admin users (dfrodriguez, kmeneses, msalazarm, dcastrog) get admin+executive roles explicitly in seed
- Seed endpoint: `POST /api/admin/seed?secret=<SEED_SECRET>` for manual re-seeding
- Auto-seed on startup if `role_report_access` table is empty

---

## Features

1. **Email Code Auth** — 8-digit code via Resend, NextAuth session, admin role management
2. **Search-First Home** — Centered search bar (cmdk), iPad-style tile icons with list view toggle
3. **Role-Based Catalog** — Users see only reports assigned to their role(s)
4. **Report Tiles** — Colorful gradient icons per report, category grouping, favorite star
5. **View Toggle** — Switch between Tiles (iPad icons) and List (OneDrive-style rows) views
6. **Full-Page Embed** — `/reports/[id]` with `<qlik-embed>` at 100vh, cookie auth + JWT
7. **Smart Search** — Full-text via Typesense, filter chips (category, tags)
8. **Admin Console** — Report CRUD, role manager, usage analytics
9. **Favorites & Pinned** — Personal pinned row in user_preferences
10. **Deep Links** — Stable URLs per report, shareable, role-gated

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| State | React Query (TanStack) |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js v5 beta-30 (Resend provider, JWT strategy) |
| Qlik Embed | `@qlik/embed-web-components` with cookie auth |
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
    api/auth/verify-code/   # 8-digit code → callback URL lookup
    api/proxy/[...path]/    # Backend proxy (sends JSON auth, not JWT)
    (auth)/login/page.tsx   # Login page (redirects if authenticated)
    (auth)/login/verify/    # Code entry page
  components/
    SearchBar.tsx           # cmdk command palette
    ReportGrid.tsx          # View toggle + categorized grid/list
    ReportCard.tsx          # Tile view (iPad icon) + list view (OneDrive row)
    ReportIcons.tsx         # Per-report icon + gradient color mapping
    QlikEmbed.tsx           # <qlik-embed> wrapper (cookie auth + getAccessToken)
    RoleGuard.tsx           # Session role check
  lib/
    auth.ts                 # NextAuth config
    api.ts                  # React Query hooks + API fetch wrapper
  next.config.mjs           # CSP headers (Qlik tenant + CDN)

backend/
  app/
    main.py                 # FastAPI app, CORS, health check, auto-seed
    config.py               # Pydantic Settings (incl SEED_SECRET)
    routers/
      deps.py               # require_user (JSON parse), require_admin
      reports.py            # GET /api/reports (role-filtered via user_roles join)
      qlik.py               # POST /api/qlik/token (RS256 JWT, cached)
      search.py             # GET /api/reports/search
      preferences.py        # GET/PATCH /api/user/preferences
      admin.py              # Admin CRUD + POST /api/admin/seed
    services/
      seed.py               # Idempotent DB seeding (dedup + upsert)
```

---

## Environment Variables

### Frontend (Vercel) — project: `2026-space-qlik-front`
```
AUTH_URL=https://analytics.unilink.space
AUTH_SECRET=<from-env>
AUTH_TRUST_HOST=true
NEXTAUTH_URL=https://analytics.unilink.space
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
ALLOWED_ORIGINS=https://analytics.unilink.space,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<from-env> (default: change-me-in-production)
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

Users seeded from time-off DB (100 users). Auth: `@unilinktransportation.com` only. Roles assigned by admin.
Admin users: dfrodriguez, kmeneses, msalazarm, dcastrog (all have admin + executive roles).

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
| Frontend | https://analytics.unilink.space (also: 2026-space-qlik-front.vercel.app) |
| Backend | https://two026-space-qlik-back.onrender.com |
| Database | Aiven PostgreSQL (`analytics_hub`) |
| Repo | https://github.com/ithomeportal/2026-space-qlik |

---

## Spec Files (local only, not in git)

| File | Contents |
|------|----------|
| `docs/SPEC-AUTH.md` | Auth flow, email code, NextAuth, roles, user seeding |
| `docs/SPEC-UI.md` | Design system, colors, typography, components |
| `docs/SPEC-QLIK.md` | Qlik embed, JWT flow, IdP setup, auth-type gotchas |
| `docs/SPEC-QLIK-INVENTORY.md` | Full app inventory with IDs, sheets, categories |
| `docs/SPEC-DATA.md` | PostgreSQL schema, API endpoints, Typesense index |
| `docs/SPEC-SEARCH.md` | Search engine, Typesense, cmdk |
| `docs/SPEC-ROADMAP.md` | Phased delivery, success metrics, lessons learned |
