# UNILINK Space (Analytics Hub) — Role-Based Qlik Dashboard Portal

> Detailed specs live in `docs/SPEC-*.md` (local only — fully gitignored).
> See [Spec Files](#spec-files) at the bottom for the index.

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
- See `docs/SPEC-RELIABILITY.md` for the full cold-start + retry strategy

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

### Render Env Vars — Always URL-Encode `$` in Connection Strings
- Render silently strips one `$` from values containing `$$` during env-var injection. See `docs/SPEC-CODE-RULES.md` §10.
- Always percent-encode special chars in DB URLs: `$` → `%24`, `*` → `%2A`, `@` → `%40`, `#` → `%23`, `?` → `%3F`
- Single-key PUT only — bulk PUT wipes the env-var list

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
- Never name a custom prop `ref` (React reserves it; minified error #284). Use `refValue`/`baseline`/`avg`. See `docs/SPEC-CODE-RULES.md` §13
- `next build` is stricter than `tsc` — always `npm run build` before pushing. See `docs/SPEC-CODE-RULES.md` §14

### Code-Made Reports (cross-cutting)
- Report-type column: `reports.report_type` (`'qlik'` | `'custom'`) + `reports.custom_path` (Next.js route); `/reports/[id]` redirects to `custom_path` when `report_type='custom'`
- Pools: external sources get their own `asyncpg` pool + env var; reports hitting the same DB share a pool via `get_*_pool` helpers in `routers/deps.py`
- Endpoints under `/api/custom/<feature>/...`, guarded by `Depends(require_report_access("<key>"))`
- ReportGuard: every default export wraps in `<ReportGuard reportKey="<key>">` — `role_report_access` table is the single source of truth (admin UI at `/admin/reports`). See `docs/SPEC-CODE-RULES.md` §15
- Tile icon: every new `CUSTOM_REPORTS` row also needs a `REPORT_MAP` entry in `frontend/components/ReportIcons.tsx` (icon + family + optional sibling tag). 10 family palettes, 3-band gradient per tile. See `docs/SPEC-UI.md` §9 + `docs/SPEC-CODE-RULES.md` §32
- Sargability: never `TRIM()` McLeod text columns in WHERE/JOIN; use `_pad_variants(values, width=N)`. See `docs/SPEC-CODE-RULES.md` §1
- v4 sparseness: executive roll-ups read `daily_production_budget_report` (CORP-only) `UNION ALL` v4-DFW. See `docs/SPEC-CODE-RULES.md` §3
- CST clock pin: `from app.clock import cst_today` in Python; bare `CURRENT_DATE`/`now()` in SQL — pools `init=_set_cst_session`. See `docs/SPEC-CODE-RULES.md` §2
- LATERAL > ROW_NUMBER: `LEFT JOIN LATERAL ... LIMIT 1` for first-match-per-key. See `docs/SPEC-CODE-RULES.md` §5
- Date-decode clamp: every user-editable date col needs `CASE … to_char(…, 'YYYY-MM-DD') … ELSE NULL` + NaN/Inf guards on per-row numerics. See `docs/SPEC-CODE-RULES.md` §4
- Full report catalog + per-report specifics: `docs/SPEC-CUSTOM-REPORTS.md`

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
- Custom reports upsert runs on every startup — adding a new entry to `CUSTOM_REPORTS` in `seed.py` is enough; `seed_custom_reports(pool)` is called from the `main.py` lifespan
- FastAPI router order matters: search router BEFORE reports router

### TagRole Canonicalization (see `docs/SPEC-ADMIN.md`)
- Canonical form: **Title-Case** for divisions (CEO, Executive, CORP, DFW, Finance, HR, IT, Operations, Procurement, Sales)
- `admin` and `super_admin` stay lowercase (singletons)
- Seed uses `role_ids_ci` (lowercased-key dict) for case-insensitive lookup
- `POST /api/admin/dedupe-roles?secret=<SEED_SECRET>` merges case duplicates and migrates all refs

### Scheduled Email Digests (see `docs/SPEC-RELIABILITY.md` §Scheduled Jobs)
- `daily_losses_alert` — 07:00 CST daily, Resend → `noreply@unilinkportal.com`, Top Losses Lanes weekly-movers (`app/services/losses_alerts.py`)
- `daily_rfp_digest` — 17:30 CST Mon-Fri, MS Graph → `ithome@unilinktransportation.com`, RFP Performance summary (`app/services/rfp_daily_digest.py`). Reuses `admin-ms-api` Entra app (Mail.Send Application perm, admin consent). See `docs/SPEC-RFP-DAILY-DIGEST.md`
- Reuse `FONT_STACK` / `MONO_STACK` constants from `rfp_daily_digest.py` for any new HTML email — Outlook font reset rule. See `docs/SPEC-CODE-RULES.md` §21

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
15. **Code-Made Reports** — Non-Qlik reports via `report_type='custom'`. Current catalog: eSavings from Carriers, 2026 Official Budget Follow Up, XRay CORP Mng, XRay DFW Mng, XRay DFW TM1..TM4, CEO Executive, HR Access Doors, DFW Access Doors, Admin Access Doors, Podium Set DFW, DFW Podium Top, Top Losses Lanes, Attrition WoW, OPs Margins, OPs Direct Compare, Sales- Attrition to OPs, OPs Customer Score, VoIP Calls Logs, Track Award Loads, Performance for RFPs, Risk Asss for Carriers, IT Tickets Mgmt, Admin Aging Cashflow, Ops Portal - Overview. **Full per-report spec in `docs/SPEC-CUSTOM-REPORTS.md`.**

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| State | React Query (TanStack) |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js v5 beta-30 (Resend, JWT strategy) |
| Scheduler | APScheduler (daily user sync + email digests) + Vercel Cron (keep-alive) |
| Qlik Embed | `@qlik/embed-web-components` with cookie auth |
| Database | PostgreSQL (Aiven) |
| Search | PostgreSQL ILIKE |
| Email | Resend + MS Graph (admin-ms-api app) |

---

## Key File Paths

```
frontend/
  app/
    layout.tsx
    page.tsx                     # Home: search + 3-column grid
    reports/[id]/page.tsx        # Full-screen Qlik embed
    reports/<custom>/page.tsx    # Code-made report (one folder per report)
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
    ReportGuard.tsx              # role_report_access gate
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
    clock.py                     # cst_today() + _set_cst_session pool init
    routers/
      deps.py                    # require_user / require_admin / require_report_access / pool factories
      reports.py                 # /api/reports, /api/apps
      qlik.py                    # Viewer + TV token endpoints
      search.py                  # /api/reports/search
      preferences.py             # /api/user/preferences
      admin.py                   # Admin CRUD + seed + sync
      <feature>.py               # One file per code-made report (see SPEC-CUSTOM-REPORTS)
    services/
      seed.py                    # Idempotent seeding
      sync_users.py              # Daily user sync
      losses_alerts.py           # 07:00 CST Resend digest
      rfp_daily_digest.py        # 17:30 CST MS-Graph digest
      msgraph_mailer.py          # Hand-rolled MS Graph send-mail (no msal)
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
DATABASE_URL=<Aiven Postgres URL — analytics_hub>
SAVINGS_DATABASE_URL=<Aiven aivn_datalake_gold URL — most code-made reports>
AUTOMATIONS_DATABASE_URL=<Aiven automations_db URL — Track Award Loads, Performance for RFPs>
FRESHSERVICE_DATABASE_URL=<Aiven fresh_services_unlk URL — IT Tickets Mgmt; percent-encode $ → %24>
TIMEOFF_DATABASE_URL=<time-off DB for daily user sync>
QLIK_TENANT_URL=https://mb01txe2h9rovgh.us.qlikcloud.com
QLIK_PRIVATE_KEY=<secret>
QLIK_ISSUER=https://analytics-hub.unilinkportal.com
QLIK_KEY_ID=analytics-hub-key-1
ALLOWED_ORIGINS=https://space.unilinkportal.com,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<secret>
TV_SECRET=<shared with frontend>
RESEND_API_KEY=<shared with frontend — daily Losses Lanes email>
SONAR_TOKEN=<FreightWaves SONAR static bearer (preferred)>
LB123_CLIENT_ID=<123LoadBoard OAuth client id>
LB123_CLIENT_SECRET=<123LoadBoard OAuth client secret>
# MS Graph — admin-ms-api app (Mail.Send Application perm + admin consent)
MS_TENANT_ID=<Unilink Entra tenant id>
MS_CLIENT_ID=<admin-ms-api client id>
MS_CLIENT_SECRET=<admin-ms-api secret — expires 2027-12-30>
MS_SEND_FROM=ithome@unilinktransportation.com
```

> **Note**: Use the same read-only role (`sa_dfrodriguez`) for
> `SAVINGS_DATABASE_URL`, `AUTOMATIONS_DATABASE_URL`, and
> `FRESHSERVICE_DATABASE_URL`. **Never bake `avnadmin` master creds into
> Render env vars** — DDL is local psql only. See `docs/SPEC-CODE-RULES.md` §8.

---

## Role Access Summary

- **TagRoles** — created/edited by admins at `/admin/roles`
- **Reports** — assigned TagRoles at `/admin/reports`; users see a report only if they share a TagRole
- **Apps** — visible to ALL authenticated users (no TagRole restriction)
- **Users** — TagRoles assigned at `/admin/users/[id]` matrix
- **Home filters** — TagRoles act as filter buttons (not access control)
- **No auto-assign** — TagRoles are 100% manual
- **Admins** — dfrodriguez, kmeneses, msalazarm, dcastrog (admin role auto-assigned); can edit Qlik App/Sheet IDs
- **Single source of truth** — `role_report_access` table (admin UI at `/admin/reports`); both `<ReportGuard>` and backend `require_report_access(...)` read it. See `docs/SPEC-CODE-RULES.md` §15

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
| `docs/SPEC-RELIABILITY.md` | Cold starts, proxy retry, keep-alive, scheduled jobs, incidents |
| `docs/SPEC-ROADMAP.md` | Phased delivery, success metrics, lessons learned |
| `docs/SPEC-CUSTOM-REPORTS.md` | Code-made (non-Qlik) reports — full per-report spec + checklist |
| `docs/SPEC-CODE-RULES.md` | Cross-cutting code rules (sargability, CST clock, asyncpg, Render env, Outlook fonts, etc.) |
| `docs/SPEC-RFP-DAILY-DIGEST.md` | RFP Performance daily email digest details |
