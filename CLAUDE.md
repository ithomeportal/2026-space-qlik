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
- CSP: allow `mb01txe2h9rovgh.us.qlikcloud.com` + `cdn.qlikcloud.com` + `login.qlik.com`
- CORS: restrict to Vercel deployment origin only
- Email auth: 8-digit code, 10-min TTL, via Resend (provider ID: "resend", NOT "email")
- Domain: use `.com` subdomains (not `.space` TLDs — Google Safe Browsing flags them)

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
- Use `@qlik/embed-web-components` with `auth-type="cookie"` — NOT `auth-type="jwt"` (invalid)
- Universal Viewer: ALL portal users share ONE Qlik identity (`portal-viewer@unilinktransportation.com`)
- Session pre-exchange: Frontend calls `POST /login/jwt-session` to exchange JWT for cookie BEFORE rendering
- JWT required claims: `sub`, `name`, `email`, `groups`, `jti`, `iat`, `nbf`, `exp`, `iss`, `aud`
- `nbf` (not-before) is MANDATORY — omitting it causes silent 400 on `/login/jwt-session`
- Web Integration ID: `UcOYHRHZf7W4ydusUB3cJPin3HHOPnit`
- JWT IdP: issuer `https://analytics-hub.unilinkportal.com`, key `analytics-hub-key-1`
- Tenant: `mb01txe2h9rovgh.us.qlikcloud.com`

### Responsive Mobile
- Below 1920px viewport = mobile mode → show only `(Mob)` prefixed Qlik reports
- Desktop (>=1920px) → show regular reports (no `(Mob)` prefix)
- Reports table has `is_mobile` boolean column; `useIsMobile()` hook detects viewport

### User Sync & TagRoles
- Users synced daily at 2:00 AM CST from People Management app (`/BOT/time-off`) via APScheduler
- Sync pulls: name, email, department, job_title (Role Name), company
- Sync deactivates offboarded users (no longer `isActive` in time-off DB)
- TagRoles are NOT auto-assigned — admins assign manually per user via admin console
- Admin users (dfrodriguez, kmeneses, msalazarm, dcastrog) auto-get admin role only
- `TIMEOFF_DATABASE_URL` must be set on Render for sync to work
- Use `emp["name"]` (bracket access) for asyncpg Records, NOT `.get("name")`
- Time-off DB `name` field is primary; `firstName`/`lastName` are fallback (23 users have null firstName)

### Database & Seeding
- Seed uses `ON CONFLICT (qlik_app_id) DO UPDATE` — idempotent, no duplicates
- Never use `dict.pop()` on module-level constants — use `dict.get()` to avoid mutation
- Seed endpoint: `POST /api/admin/seed?secret=<SEED_SECRET>`
- Auto-seed on startup if `role_report_access` table is empty
- Apps tables (`apps`, `app_role_access`) created on startup AND in seed — must exist before API use
- New columns added via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` at startup (no migrations needed)

### Render Cold Starts
- Render free tier spins down after inactivity — cold starts take 30-60s
- Proxy route has `maxDuration=60` and 45s fetch timeout to survive cold starts
- React Query retries 3x with exponential backoff (2s, 4s, 8s)
- ReportGrid shows friendly "server waking up" message with retry button on error

### App Favicons
- Favicons fetched from app URL directly: tries `/icon.svg`, `/favicon.svg`, `/favicon.ico`, then HTML `<link rel="icon">`
- Google favicon API is last resort; default globe icon (726/362 bytes) is rejected
- Stored as base64 data URIs in `icon_data` column — no external CSP needed
- Auto-backfill on startup for apps with null or PNG placeholder icons

---

## Features

1. **Email Code Auth** — 8-digit code via Resend, NextAuth session, admin role management
2. **Search-First Home** — Centered search bar (cmdk), iPad-style tile icons with list view toggle
3. **TagRole-Based Access** — Users see only reports/apps with matching TagRoles (assigned by admin)
4. **Responsive Mobile** — <1920px shows (Mob) Qlik apps optimized for small screens
5. **Viewer-Only Embed** — `analytics/sheet` with `toolbar=false`, JWT "Viewers" group
6. **Full-Page Embed** — `/reports/[id]` with `<qlik-embed>` at 100vh
7. **Smart Search** — Full-text via Typesense, filter chips (category, tags)
8. **Admin Console** — Reports/Apps CRUD (with Note field), TagRole manager, user management with matrix view, usage analytics
9. **Apps (External Links)** — External links with favicon icons, TagRole access, open in new tab
10. **Daily User Sync** — APScheduler syncs users from People Management app at 2am CST
11. **User Access Matrix** — Full-page `/admin/users/[id]` with report×TagRole matrix view

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| State | React Query (TanStack) |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js v5 beta-30 (Resend provider, JWT strategy) |
| Scheduler | APScheduler (daily user sync) |
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
    page.tsx                # Home: search bar + report grid + apps (responsive)
    reports/[id]/page.tsx   # Full-screen Qlik embed viewer
    admin/
      layout.tsx            # Admin sidebar (Dashboard, Reports, Apps, Tag Roles, Users)
      page.tsx              # Usage analytics dashboard
      reports/page.tsx      # Report CRUD + TagRole assignment per report
      apps/page.tsx         # App CRUD (external links) + TagRole assignment
      roles/page.tsx        # TagRole CRUD (create, edit name/description, delete)
      users/page.tsx        # User list with sortable columns
      users/[id]/page.tsx   # User detail: TagRole assignment + report access matrix
    api/auth/[...nextauth]/ # NextAuth handlers
    api/proxy/[...path]/    # Backend proxy (sends JSON auth, not JWT)
    (auth)/login/page.tsx   # Login page (redirects if authenticated)
  components/
    SearchBar.tsx           # cmdk command palette
    ReportGrid.tsx          # View toggle + categorized grid/list + apps section
    ReportCard.tsx          # Report tile/list + App tile/list (favicon from URL)
    QlikEmbed.tsx           # <qlik-embed> wrapper (universal viewer + session pre-exchange)
  lib/
    auth.ts                 # NextAuth config
    api.ts                  # React Query hooks + API fetch wrapper (reports, apps, prefs)
    use-is-mobile.ts        # Viewport detection hook (<1920px = mobile)
  next.config.mjs           # CSP headers (Qlik + Google favicons)

backend/
  app/
    main.py                 # FastAPI app, CORS, health check, auto-seed, apps tables, APScheduler
    config.py               # Pydantic Settings (incl SEED_SECRET, TIMEOFF_DATABASE_URL)
    routers/
      deps.py               # require_user (JSON parse), require_admin
      reports.py            # GET /api/reports, GET /api/apps (both role-filtered)
      qlik.py               # POST /api/qlik/viewer-token (universal viewer JWT)
      search.py             # GET /api/reports/search
      preferences.py        # GET/PATCH /api/user/preferences
      admin.py              # Admin CRUD: reports, apps, roles, users, seed, sync
    services/
      seed.py               # Idempotent seeding: reports, roles, apps tables
      sync_users.py         # Daily user sync from time-off DB (no auto-assign)
```

---

## Environment Variables

### Frontend (Vercel) — project: `2026-space-qlik-front`
```
AUTH_URL=https://space.unilinkportal.com
AUTH_SECRET=<from-env>
AUTH_TRUST_HOST=true
NEXTAUTH_URL=https://space.unilinkportal.com
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
ALLOWED_ORIGINS=https://space.unilinkportal.com,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<from-env>
TIMEOFF_DATABASE_URL=<from-env> (time-off DB for daily user sync)
```

---

## TagRole Access Model

- **TagRoles** are created/edited by admins at `/admin/roles`
- **Reports** are assigned TagRoles at `/admin/reports` (pencil icon per report)
- **Apps** are assigned TagRoles at `/admin/apps` ("All TagRoles" toggle or select individual)
- **Users** are assigned TagRoles at `/admin/users/[id]` (full-page matrix view)
- **Access rule**: User sees a report/app only if they share at least one TagRole with it
- **No auto-assign**: TagRoles are 100% manually assigned by admins
- Admin users: dfrodriguez, kmeneses, msalazarm, dcastrog (admin role auto-assigned)

---

## Qlik Tenant

- **Tenant**: `mb01txe2h9rovgh.us.qlikcloud.com`
- **Tenant ID**: `ZC6dict00GLAZhISVRVWKm4d-l105j0n`
- **JWT IdP**: Configured (ID: `69b30b03dbb54989a11adb6b`)
- **Viewers Group**: ID `69b4c6eec98c45424617135b` — "consumer" on all shared spaces
- **19 desktop + 12 mobile apps** across 7 spaces (see docs/SPEC-QLIK-INVENTORY.md)

---

## Deployments

| Service | URL |
|---------|-----|
| Frontend | https://space.unilinkportal.com (also: 2026-space-qlik-front.vercel.app) |
| Backend | https://two026-space-qlik-back.onrender.com |
| Database | Aiven PostgreSQL (`analytics_hub`) |
| Repo | https://github.com/ithomeportal/2026-space-qlik |

---

## Spec Files (local only, not in git)

| File | Contents |
|------|----------|
| `docs/SPEC-AUTH.md` | Auth flow, email code, NextAuth, roles, user seeding |
| `docs/SPEC-UI.md` | Design system, colors, typography, components |
| `docs/SPEC-QLIK.md` | Qlik embed, JWT flow, IdP setup, auth-type gotchas, lessons learned |
| `docs/SPEC-QLIK-INVENTORY.md` | Full app inventory with IDs, sheets, categories |
| `docs/SPEC-DATA.md` | PostgreSQL schema, API endpoints, Typesense index |
| `docs/SPEC-SEARCH.md` | Search engine, Typesense, cmdk |
| `docs/SPEC-ROADMAP.md` | Phased delivery, success metrics, lessons learned |
| `docs/SPEC-ADMIN.md` | Admin console, TagRole model, user sync, apps, lessons learned |
