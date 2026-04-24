# UNILINK Space (Analytics Hub) — Role-Based Qlik Dashboard Portal

> For detailed specs see `docs/SPEC-*.md` (local only, not in git).

---

## Critical Rules

### Git & Docs
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Never commit secrets (.env, credentials, API keys)
- `docs/` is fully gitignored — ALL documentation is local-only, no exceptions
- Push to GitHub directly via CLI; Vercel/Render auto-deploy from the repo
- Never include author / co-author names in commits or LICENSE

### Server Actions & API Patterns
- All mutations via Next.js Server Actions (not API routes) except auth
- FastAPI backend: JWT generation, report catalog CRUD, search, usage analytics
- API envelope: `{ success: boolean, data?: T, error?: string, meta?: { total, page, limit } }`
- Validate inputs with Zod (frontend) and Pydantic (backend)
- Next.js proxy sends user info as JSON in Authorization header (NOT a JWT) — backend parses with `json.loads`
- Proxy retries GET on 502/503/504 up to 3× (5s, 10s); mutations never retry; returns 503+`Retry-After:30` on total failure
- See `docs/SPEC-RELIABILITY.md` for full cold-start + retry strategy

### Security (Non-Negotiable)
- NO hardcoded secrets — all via environment variables
- Qlik JWTs: 60-min expiry, silent refresh before expiry
- Rate limiting: 300 req/min standard, 10 req/min for token generation
- CSP allows: `*.qlikcloud.com`, `cdn.qlikcloud.com`, `cdn.jsdelivr.net`, `login.qlik.com`, `*.launchdarkly.com`, `events.launchdarkly.com`, `api.qlikdataengineering.com`, `sqs.us-east-1.amazonaws.com`, `two026-space-qlik-back.onrender.com`
- CORS: restrict to Vercel deployment origin only
- Email auth: 8-digit code, 10-min TTL, via Resend (provider ID: `"resend"`, NOT `"email"`)
- Domain: use `.com` subdomains (not `.space` TLDs — Google Safe Browsing flags them)

### Vercel Env Var Management
- ALWAYS run `vercel env` commands from `frontend/` directory
- Use `printf 'value' | npx vercel env add NAME production` — NOT `echo` (adds newline)
- Never run `vercel --prod` from repo root — use git push for auto-deploy
- After changing env vars, push empty commit to trigger redeploy

### NextAuth v5 Gotchas
- Provider ID is `"resend"` not `"email"` — affects `signIn()` and callback URLs
- Requires `AUTH_SECRET` (not just `NEXTAUTH_SECRET`) + `AUTH_TRUST_HOST=true`
- Tokens are hashed before DB storage — code verification uses `email_codes` table, NOT `verification_tokens`
- Login page must check session and redirect authenticated users to `/`

### Code Style
- Immutable updates only (spread operator, no mutation)
- Files < 400 lines (800 max), functions < 50 lines
- No `console.log` in production (`console.warn` allowed for diagnostics)
- ONLY light mode — block dark mode
- shadcn/ui Dialog uses `@base-ui/react` (React 19) — avoid Base UI in any interactive component on React 18
- Search bar is pure React/HTML (no cmdk / Base UI / Radix)

### Qlik Embedding (summary — see `docs/SPEC-QLIK.md`)
- Use `@qlik/embed-web-components` with `auth-type="cookie"` — NOT `"jwt"` (invalid)
- Universal Viewer: ALL portal users share ONE Qlik identity (`portal-viewer@unilinktransportation.com`)
- Session pre-exchange: `POST /login/jwt-session` BEFORE rendering; Promise singleton prevents races; 3 retries with backoff
- JWT required claims: `sub`, `name`, `email`, `groups`, `jti`, `iat`, `nbf`, `exp`, `iss`, `aud` — `nbf` is MANDATORY
- Web Integration ID: `UcOYHRHZf7W4ydusUB3cJPin3HHOPnit`
- Tenant: `mb01txe2h9rovgh.us.qlikcloud.com`
- Classic Embed Mode toggle for Dashboard Bundle objects (Date Picker, Variable Input, etc.)

### TV Display (`/dfw-podium` — see `docs/SPEC-QLIK.md`)
- Standalone route handler (not React page), serves raw HTML
- JWT→cookie via `/api/qlik/tv-token` with `TV_SECRET` (must match on Vercel + Render)
- Auto-refresh hourly; retry after 30s on error
- RiseVision URL: `https://space.unilinkportal.com/dfw-podium`

### Responsive Mobile
- <1920px viewport = mobile mode → only `(Mob)` prefixed Qlik reports
- Reports table has `is_mobile` column; `useIsMobile()` hook detects viewport

### User Sync & TagRoles (see `docs/SPEC-ADMIN.md`)
- Daily sync at 2 AM CST from People Management app via APScheduler
- TagRoles NOT auto-assigned — admins assign manually per user
- Admin users (dfrodriguez, kmeneses, msalazarm, dcastrog) auto-get admin role
- Use `emp["name"]` (bracket access) for asyncpg Records, NOT `.get("name")`

### Database & Seeding (see `docs/SPEC-DATA.md`)
- Seed uses `ON CONFLICT (qlik_app_id) DO UPDATE` — idempotent (partial index on `qlik_app_id IS NOT NULL`)
- Never `dict.pop()` on module-level constants — use `.get()`
- Auto-seed on startup if `role_report_access` is empty
- **Custom reports upsert runs on every startup** regardless of the empty-check above — adding a new entry to `CUSTOM_REPORTS` in `seed.py` is enough, the next Render deploy will insert the row via `seed_custom_reports(pool)` (called from `main.py` lifespan). No manual `POST /api/admin/seed` needed.
- FastAPI router order matters: search router BEFORE reports router

### Code-Made Reports (see `docs/SPEC-CUSTOM-REPORTS.md` for full spec + lessons)
- `reports.report_type` (`'qlik'` | `'custom'`) + `reports.custom_path` (Next.js route); `/reports/[id]` redirects to `custom_path` when `report_type='custom'`
- External data sources get their own `asyncpg` pool + env var; reports hitting the same DB share a pool via `get_datalake_gold_pool` in `routers/deps.py`
- Endpoints live under `/api/custom/<feature>/...`, guarded by `require_tag_role(*allowed)` (admin bypasses, case-insensitive)
- **Sargability rule** — McLeod `aivn_datalake_gold` text columns (`team_id`, `company_id`, `status`, `stop_type`, `edi_standard_code`) are stored inconsistently as `'TEAM1'` or `'TEAM1   '` (3-space-padded). Never wrap in `TRIM()` inside WHERE/JOIN predicates — use `col = ANY(ARRAY['TEAM1','TEAM1   ', ...])` via the `_pad_variants()` helper. TRIM is fine in SELECT/GROUP BY output, never in filter predicates.
- **v4 sparseness rule** — `mcleod_gld_budget_report_v4` lags for the current month; for executive roll-ups (KPIs, Summary by Team, All Teams Performance, Profit-TM) read `daily_production_budget_report` (6h n8n refresh) joined to a customer→team mapping derived from v4. Keep v4 for load/lane-level panels only.
- **Placeholder rule** — when a query needs its own leading `$1` for a CTE, seed it into `params` **before** calling `_scope_where`, don't pass it as an extra positional at `pool.fetch` time — otherwise `_scope_where`'s placeholders shift and `BETWEEN $N-1 AND $N` receives a `text[]` instead of a `date`.
- **Current catalog** (see SPEC-CUSTOM-REPORTS.md for full details):

| Report | Path | Roles | Primary source(s) |
|---|---|---|---|
| eSavings from Carriers | `/reports/esavings-carriers` | CEO, Executive, Procurement, Finance, CORP, DFW | `carriers_savings_results_report` |
| 2026 Official Budget Follow Up | `/reports/budget-followup-2026` | CEO, Executive, Operations, Finance, CORP, DFW | `daily_production_budget_report` + v4 team map |
| XRay CORP Mng | `/reports/xray-corp-mng` | CEO, Executive, CORP, Operations, Finance | v4 + scorecard + movement + budget_report + savings |
| CEO Executive | `/reports/ceo-executive` | **admin + CEO only** | Overview roll-ups: `daily_production_budget_report` + v4 team map; detail panels: v4 |
| Podium Set DFW | `/reports/podium-dfw` | admin + DFW | `mcleod_gld_order_post_hist` (Rate Conf Received, latest/order) LEFT JOIN `mcleod_gld_budget_report_v4`; replaces Qlik `0a0c7a49-…`; 15-min auto-refresh; DB is already CST (no `AT TIME ZONE`) |

### TagRole Canonicalization (see `docs/SPEC-ADMIN.md`)
- Canonical form: **Title-Case** for divisions (CEO, Executive, CORP, DFW, Finance, HR, IT, Operations, Procurement, Sales)
- `admin` and `super_admin` stay lowercase (singletons)
- Seed uses `role_ids_ci` (lowercased-key dict) for case-insensitive lookup
- `POST /api/admin/dedupe-roles?secret=<SEED_SECRET>` merges case duplicates and migrates all refs

### Render Cold Starts (see `docs/SPEC-RELIABILITY.md`)
- Free tier spins down after ~15 min inactivity — cold starts 30–60s
- Vercel cron `/api/cron/keepalive` pings `/api/health` every 10 min
- Proxy retries GET on 5xx 3× (5s, 10s); React Query 5× (2s→30s); skip 401/403
- Favicon backfill MUST run as background `asyncio.create_task` — never block lifespan

### App Favicons
- Fetched from app URL: tries `/icon.svg`, `/favicon.svg`, `/favicon.ico`, then HTML `<link rel="icon">`
- Google favicon API is last resort; default globe (726/362 bytes) is rejected
- Stored as base64 data URIs in `icon_data` (no CSP needed)

---

## Features (1-line each — see spec files for details)

1. **Email Code Auth** — 8-digit code via Resend, NextAuth session
2. **3-Column Home** — TagRole filters | Reports | Apps, sorted by usage
3. **TagRole-Based Access** — Reports filtered by TagRole; Apps visible to all
4. **Responsive Mobile** — <1920px forces list view + `(Mob)` reports
5. **Viewer-Only Embed** — `analytics/sheet` with toolbar off, Viewers group JWT
6. **Full-Page Embed** — `/reports/[id]` 100vh, auto-picks classic vs analytics
7. **Inline Search** — DB-backed, title/description/note/tags, 300ms debounce
8. **Admin Console** — Reports/Apps/TagRoles/Users CRUD + matrix view
9. **Apps (External Links)** — Favicon-iconed links, visible to all users
10. **Daily User Sync** — APScheduler from People Management DB at 2 AM CST
11. **User Access Matrix** — `/admin/users/[id]` report × TagRole matrix
12. **Classic Embed Mode** — Per-report toggle for Dashboard Bundle reports
13. **TV Display** — `/dfw-podium` standalone Qlik fullscreen for RiseVision
14. **Keep-Alive Cron** — 10-min backend ping to prevent Render cold starts
15. **Code-Made Reports** — Non-Qlik reports via `report_type='custom'`; current: eSavings from Carriers, 2026 Official Budget Follow Up, XRay CORP Mng

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| State | React Query (TanStack) |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js v5 beta-30 (Resend, JWT strategy) |
| Scheduler | APScheduler (daily user sync) + Vercel Cron (keep-alive) |
| Qlik Embed | `@qlik/embed-web-components` with cookie auth |
| Database | PostgreSQL (Aiven) |
| Search | PostgreSQL ILIKE |
| Email | Resend |

---

## Key File Paths

```
frontend/
  app/
    layout.tsx
    page.tsx                     # Home: search + 3-column grid
    reports/[id]/page.tsx        # Full-screen Qlik embed
    admin/
      layout.tsx                 # Admin sidebar
      page.tsx                   # Usage analytics
      reports/page.tsx           # Report CRUD + TagRole assignment
      apps/page.tsx              # App CRUD
      roles/page.tsx             # TagRole CRUD
      users/page.tsx             # User list
      users/[id]/page.tsx        # User detail + access matrix
    dfw-podium/route.ts          # TV display (JWT→cookie)
    api/auth/[...nextauth]/      # NextAuth handlers
    api/proxy/[...path]/route.ts # Backend proxy w/ retry logic
    api/cron/keepalive/route.ts  # Vercel cron → backend /api/health
    (auth)/login/page.tsx
  components/
    SearchBar.tsx
    ReportGrid.tsx
    ReportCard.tsx
    QlikEmbed.tsx                # Session exchange + retry + singleton
    Providers.tsx                # React Query w/ 5× retry, skip 401/403
  lib/
    auth.ts
    api.ts
    use-is-mobile.ts
    use-debounce.ts
  next.config.mjs                # CSP headers
  vercel.json                    # Cron schedule

backend/
  app/
    main.py                      # FastAPI, CORS, lifespan, APScheduler
    config.py                    # Pydantic Settings
    routers/
      deps.py                    # require_user / require_admin
      reports.py                 # /api/reports, /api/apps
      qlik.py                    # Viewer + TV token endpoints
      search.py                  # /api/reports/search
      preferences.py             # /api/user/preferences
      admin.py                   # Admin CRUD + seed + sync
    services/
      seed.py                    # Idempotent seeding
      sync_users.py              # Daily user sync
```

---

## Environment Variables

### Frontend (Vercel — `2026-space-qlik-front`)
```
AUTH_URL=https://space.unilinkportal.com
AUTH_SECRET=<secret>
AUTH_TRUST_HOST=true
NEXTAUTH_URL=https://space.unilinkportal.com
NEXTAUTH_SECRET=<secret>
DATABASE_URL=postgresql://...
RESEND_API_KEY=<secret>
BACKEND_URL=https://two026-space-qlik-back.onrender.com
NEXT_PUBLIC_QLIK_TENANT=mb01txe2h9rovgh.us.qlikcloud.com
TV_SECRET=<shared with backend>
```

### Backend (Render)
```
DATABASE_URL=<Aiven Postgres URL>
SAVINGS_DATABASE_URL=<Aiven aivn_datalake_gold URL — powers eSavings from Carriers, 2026 Official Budget Follow Up, AND XRay CORP Mng>
QLIK_TENANT_URL=https://mb01txe2h9rovgh.us.qlikcloud.com
QLIK_PRIVATE_KEY=<secret>
QLIK_ISSUER=https://analytics-hub.unilinkportal.com
QLIK_KEY_ID=analytics-hub-key-1
ALLOWED_ORIGINS=https://space.unilinkportal.com,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<secret>
TV_SECRET=<shared with frontend>
TIMEOFF_DATABASE_URL=<time-off DB for daily user sync>
```

---

## Role Access Summary

- **TagRoles** — created/edited by admins at `/admin/roles`
- **Reports** — assigned TagRoles at `/admin/reports`; users see a report only if they share a TagRole
- **Apps** — visible to ALL authenticated users (no TagRole restriction)
- **Users** — TagRoles assigned at `/admin/users/[id]` matrix
- **Home filters** — TagRoles act as filter buttons (not access control)
- **No auto-assign** — TagRoles are 100% manual
- **Admins** — dfrodriguez, kmeneses, msalazarm, dcastrog (admin role auto-assigned); can edit Qlik App/Sheet IDs

---

## Qlik Tenant

- **Tenant**: `mb01txe2h9rovgh.us.qlikcloud.com`
- **Tenant ID**: `ZC6dict00GLAZhISVRVWKm4d-l105j0n`
- **JWT IdP ID**: `69b30b03dbb54989a11adb6b`
- **Viewers Group ID**: `69b4c6eec98c45424617135b` (consumer on all shared spaces)
- **Web Integration ID**: `UcOYHRHZf7W4ydusUB3cJPin3HHOPnit`
- 19 desktop + 12 mobile apps across 7 spaces (see `docs/SPEC-QLIK-INVENTORY.md`)

---

## Deployments

| Service | URL |
|---------|-----|
| Frontend | https://space.unilinkportal.com (alt: `2026-space-qlik-front.vercel.app`) |
| Backend | https://two026-space-qlik-back.onrender.com |
| Database | Aiven PostgreSQL (`analytics_hub`) |
| Repo | https://github.com/ithomeportal/2026-space-qlik |

---

## Spec Files (local only — `docs/`, gitignored)

| File | Contents |
|------|----------|
| `docs/SPEC-AUTH.md` | Auth flow, email code, NextAuth, roles, user seeding |
| `docs/SPEC-UI.md` | Design system, colors, typography, 3-column layout |
| `docs/SPEC-QLIK.md` | Qlik embed, JWT, IdP setup, TV display, lessons learned |
| `docs/SPEC-QLIK-INVENTORY.md` | Full app inventory with IDs, sheets, categories |
| `docs/SPEC-DATA.md` | PostgreSQL schema, API endpoints |
| `docs/SPEC-SEARCH.md` | Search engine, PostgreSQL ILIKE |
| `docs/SPEC-ADMIN.md` | Admin console, TagRoles, user sync, apps |
| `docs/SPEC-RELIABILITY.md` | Cold starts, proxy retry, keep-alive, incidents, lessons |
| `docs/SPEC-ROADMAP.md` | Phased delivery, success metrics, lessons learned |
| `docs/SPEC-CUSTOM-REPORTS.md` | Code-made (non-Qlik) reports: pattern, checklist, eSavings spec |
