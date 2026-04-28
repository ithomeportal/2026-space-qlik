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
- Never name a custom prop `ref` (e.g. for a chart's reference/baseline/avg value) — React reserves it and validates the value at element-creation; passing a non-callback throws minified error #284. Use `refValue`/`baseline`/`avg` instead. Bit us twice on Attrition WoW: Trends tab `<BarPanel ref={…}>` (commit `0112ddf`), then the merged Pivots tab `<StatusDot ref={…}>` only crashed on the *By Customer* view because *by Team* didn't render the dot (commit `2d86800`). Audit small inline children — status dots, delta arrows, sparkline tips — not just the chart panels
- Every code-made report wraps its default export in `<RoleGuard roles={[...REPORT_ACCESS["<key>"]]}>` (`frontend/components/RoleGuard.tsx`) so users without an allowed TagRole see a single clean access-denied banner instead of every panel firing its own 403. Source-of-truth role lists live in `frontend/lib/report-access.ts` and must mirror `backend/app/services/seed.py::CUSTOM_REPORTS` + each router's `*_ROLES` tuple. Match is case-insensitive; admin always bypasses

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
- **Sargability rule** — McLeod `aivn_datalake_gold` text columns (`team_id varchar(8)`, `company_id varchar(4)`, `status`, `stop_type`, `edi_standard_code`) arrive padded to the column's declared width. Never `TRIM()` in WHERE/JOIN; use `col = ANY(_pad_variants(values, width=<N>))`. TRIM is fine in SELECT/GROUP BY output. If one side of a JOIN trims, the other must trim too. (Full pattern + worked example: SPEC-CUSTOM-REPORTS.md)
- **v4 sparseness rule** — `mcleod_gld_budget_report_v4` lags current month; executive roll-ups read `daily_production_budget_report` joined to a v4 customer→team map. **Caveat**: `daily_production_budget_report` is CORP-only — any Overview that needs DFW must `UNION ALL` v4-DFW production (`_production_cte()` in `ceo_executive.py`). Zero customer overlap CORP↔DFW so no double-count.
- **Sargability for `origin_actual_departure`** — never `origin_actual_departure::date BETWEEN $s AND $e` (kills `idx_v4_dep`). Use half-open `origin_actual_departure >= $s AND origin_actual_departure < ($e::date + 1)`. ~30× faster.
- **First-match-per-key joins** — use `LEFT JOIN LATERAL (... ORDER BY ... LIMIT 1) ON TRUE` not `ROW_NUMBER() WHERE rn=1` CTE; ~40× faster with a supporting `(key1, key2, sort_col)` btree. Movement ⇒ `idx_movement_order_company_mv`.
- **Placeholder rule** — seed CTE-leading `$1` into `params` **before** calling `_scope_where`; never pass extra positional at `pool.fetch` time, or downstream `BETWEEN $N-1 AND $N` placeholders shift.
- **CST clock rule** — Render runs containers in UTC and Aiven defaults sessions to UTC. Datalake is already CST. To keep the app's notion of "today" aligned with the data: Python side use `from app.clock import cst_today` (never `date.today()`); SQL side use bare `CURRENT_DATE` / `now()` / `date_trunc(...)` — every asyncpg pool runs `init=_set_cst_session` (`SET TIME ZONE 'America/Chicago'`) at connect time, so they all resolve to CST without per-query `AT TIME ZONE` rewrites. Bruno caught this on XRay CORP Mng on 2026-04-27 (commit `123e5b0`): "Yesterday=Apr 27" while CST clock was still on Apr 27. Affects every code-made report between 18:00–23:59 CST.
- **Current catalog** (one-line; full specs/lessons in `docs/SPEC-CUSTOM-REPORTS.md`):

| Report | Path | Roles | Primary source |
|---|---|---|---|
| eSavings from Carriers | `/reports/esavings-carriers` | CEO, Executive, Procurement, Finance, CORP, DFW | `carriers_savings_results_report` + `lane_market_rates` (SONAR + 123LB monthly cache). Quarterly base = simple avg of prior-quarter non-zero monthly avgs; **no prior-quarter activity → base=0, variance=0** (refined 2026-04-28 — replaced the silent 2025-fallback that produced fake overpays). UI shows `base_month` chip under BASE $ with a red dot on stale rows. |
| 2026 Official Budget Follow Up | `/reports/budget-followup-2026` | CEO, Executive, Operations, Finance, CORP, DFW | `daily_production_budget_report` + v4 team map |
| XRay CORP Mng | `/reports/xray-corp-mng` | CEO, Executive, CORP, Operations, Finance | v4 + scorecard + movement + budget_report + savings |
| CEO Executive | `/reports/ceo-executive` | **admin + CEO only** | `_production_cte` UNIONs `daily_production_budget_report` (CORP) with v4-DFW for Overview roll-ups; detail tabs read v4. Perf indexes: `idx_v4_dep`, `idx_movement_order_company_mv`. See SPEC-CUSTOM-REPORTS.md |
| Podium Set DFW | `/reports/podium-dfw` | admin + DFW | `mcleod_gld_order_post_hist` ⨝ v4; replaces Qlik `0a0c7a49-…`; 15-min auto-refresh; client-side Team pill filter |
| Top Losses Lanes | `/reports/losses-lanes` | CEO, Executive, CORP, DFW, Operations, Finance | v4; scope TEAM1-5 + TEAM-DFW / TMS,TMS3 / status D,P; excludes UNILINK + OILTEX; `margin_amt<0`; daily 7 AM CST weekly-movers email |
| OPs Margins | `/reports/ops-margins` | CEO, Executive, CORP, DFW, Operations, Finance | v4 (+ movement for carrier name); 6 tabs; always-on Trend + Margin histogram; same scope as Losses Lanes |
| OPs Direct Compare | `/reports/ops-direct-compare` | CEO, Executive, CORP, DFW, Operations, Finance | v4; two independent data1/data2 panels with center delta; cached 12-month trend; same scope as OPs Margins |
| Sales- Attrition to OPs | `/reports/sales-attrition-to-ops` | CEO, Executive, Sales, CORP, DFW, Operations, Finance | v4; per-customer attrition w/ days-since color band; fixed 13-month strip ignores Date filter |
| Attrition WoW | `/reports/attrition-wow` | CEO, Executive, Sales, CORP, DFW, Operations, Finance | v4; ISO Mon-Sun weeks (current excluded); **3 tabs (post-Bruno 2026-04-27)**: Overview · Reactive Customers · Trends & Pivots (merged). Cream-bg L8W avg col; integer AVG LOADS; by-Customer pivot has red/yellow/green status dot vs 8w avg; Trends bars use panel color above-avg, gray below. Reactive bucket order: 2-4W before LW |
| VoIP Calls Logs | `/reports/voip-calls-logs` | **everyone** | `vonage_gld_by_user` (1 GB, ~1.6M rows, fresh through current minute, no n8n); WTD default; indexes `idx_vonage_gld_by_user_start{,_dir}` |
| OPs Customer Score | `/reports/ops-customer-score` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_scorecard`; 4 tabs (PU/DEL × Overview/Detail); KPI cards + 12mo/10wk charts ignore Date filter and cache 10 min |
| Track Award Loads | `/reports/track-award-loads` | CEO, Executive, Sales, Procurement, Operations, Finance, CORP, DFW | `contract_performance_analysis` in **`automations_db`** (NOT `aivn_datalake_gold` — own pool, `AUTOMATIONS_DATABASE_URL` env var) ⨝ `awards_tracker_registration_source` (per-lane RPM/Min Chg/All-in rates via natural-key LEFT JOIN). Replaces legacy Qlik `949cafc8-…` (unilink.us tenant — not embeddable). n8n daily 02:25 (`3XkU4PfCm4EBYgTl Contract Performance Analysis`) keeps 15-day rolling window; **always pin to `analysis_date = MAX` snapshot** or aggregates inflate by ~15×. 4 filter pills · 4 KPI containers · 4 detail tables. Partial index `idx_cpa_primary_latest` covers the snapshot+filter path. Days-to-Exp red banner + WoW Δ on Total Actual Volume (joins natural key — destination `audit_id` is SERIAL, not stable across snapshots) |

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
15. **Code-Made Reports** — Non-Qlik reports via `report_type='custom'`; current: eSavings from Carriers, 2026 Official Budget Follow Up, XRay CORP Mng, CEO Executive, HR Access Doors, Podium Set DFW, Top Losses Lanes, Attrition WoW, OPs Margins, OPs Direct Compare, Sales- Attrition to OPs, OPs Customer Score, VoIP Calls Logs, Track Award Loads

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
SAVINGS_DATABASE_URL=<Aiven aivn_datalake_gold URL — powers MOST code-made reports (eSavings, Budget Follow Up, XRay CORP Mng, CEO Executive, HR Access Doors, Podium Set DFW, Top Losses Lanes, Attrition WoW, OPs Margins/Direct Compare/Customer Score, Sales-Attrition to OPs, VoIP Calls Logs)>
AUTOMATIONS_DATABASE_URL=<Aiven automations_db URL — powers ONLY Track Award Loads (n8n's contract_performance_analysis). Same Aiven cluster as SAVINGS_DATABASE_URL, just dbname=automations_db. Use the same read-only role you use for SAVINGS_DATABASE_URL — do NOT bake avnadmin in here.>
QLIK_TENANT_URL=https://mb01txe2h9rovgh.us.qlikcloud.com
QLIK_PRIVATE_KEY=<secret>
QLIK_ISSUER=https://analytics-hub.unilinkportal.com
QLIK_KEY_ID=analytics-hub-key-1
ALLOWED_ORIGINS=https://space.unilinkportal.com,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<secret>
TV_SECRET=<shared with frontend>
TIMEOFF_DATABASE_URL=<time-off DB for daily user sync>
RESEND_API_KEY=<shared with frontend — powers daily Losses Lanes weekly-movers email at 7 AM CST>
SONAR_TOKEN=<FreightWaves SONAR static bearer (preferred)>          # eSavings SONAR $ column
# SONAR_USERNAME / SONAR_PASSWORD — fallback if SONAR_TOKEN is not set
LB123_CLIENT_ID=<123LoadBoard OAuth client id>                       # eSavings 123LB $ column
LB123_CLIENT_SECRET=<123LoadBoard OAuth client secret>
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
| `docs/SPEC-CUSTOM-REPORTS.md` | Code-made (non-Qlik) reports: pattern, checklist, eSavings spec, Track Award Loads spec, audit_id SERIAL trap, CST clock pin |
