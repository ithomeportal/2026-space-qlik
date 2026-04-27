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
- **Sargability rule** — McLeod `aivn_datalake_gold` text columns (`team_id varchar(8)`, `company_id varchar(4)`, `status varchar(1)`, `stop_type varchar(2)`, `edi_standard_code varchar(40)`) arrive inconsistently: some unpadded (`'TEAM1'`), some right-padded to the column's declared width (`'TEAM1   '`, `'TMS '`). **Padding is per-column width, not a constant.** Never wrap in `TRIM()` inside WHERE/JOIN predicates — use `col = ANY(_pad_variants(values, width=<N>))`, passing the column's declared `character_maximum_length`. TRIM is fine in SELECT/GROUP BY output, never in filter predicates. Also: when a CTE TRIMs a column on one side (e.g. `TRIM(company_id) AS company_id_key`), the JOIN must TRIM the other side too — comparing padded `br4.company_id` ('TMS ') to trimmed `otp.company_id_key` ('TMS') silently misses every row.
- **v4 sparseness rule** — `mcleod_gld_budget_report_v4` lags for the current month; for executive roll-ups (KPIs, Summary by Team, All Teams Performance, Profit-TM) read `daily_production_budget_report` (6h n8n refresh) joined to a customer→team mapping derived from v4. Keep v4 for load/lane-level panels only.
- **Placeholder rule** — when a query needs its own leading `$1` for a CTE, seed it into `params` **before** calling `_scope_where`, don't pass it as an extra positional at `pool.fetch` time — otherwise `_scope_where`'s placeholders shift and `BETWEEN $N-1 AND $N` receives a `text[]` instead of a `date`.
- **Current catalog** (see SPEC-CUSTOM-REPORTS.md for full details):

| Report | Path | Roles | Primary source(s) |
|---|---|---|---|
| eSavings from Carriers | `/reports/esavings-carriers` | CEO, Executive, Procurement, Finance, CORP, DFW | `carriers_savings_results_report` |
| 2026 Official Budget Follow Up | `/reports/budget-followup-2026` | CEO, Executive, Operations, Finance, CORP, DFW | `daily_production_budget_report` + v4 team map |
| XRay CORP Mng | `/reports/xray-corp-mng` | CEO, Executive, CORP, Operations, Finance | v4 + scorecard + movement + budget_report + savings |
| CEO Executive | `/reports/ceo-executive` | **admin + CEO only** | Overview roll-ups: `daily_production_budget_report` + v4 team map; detail panels: v4. Scope includes CORP (team_id TEAM1-5) **and DFW** (team_id TEAM-DFW → sub-teams TM1-TM4 via `v4.team` col). Division pill (All/CORP/DFW) narrows the team_id universe; Team pill auto-swaps between TEAM1-5 (CORP) and TM1-4 (DFW). DFW sub-team filter uses `TRIM(team)=…` only AFTER the sargable team_id prune |
| Podium Set DFW | `/reports/podium-dfw` | admin + DFW | `mcleod_gld_order_post_hist` (Rate Conf Received, latest/order) LEFT JOIN `mcleod_gld_budget_report_v4`; replaces Qlik `0a0c7a49-…`; 15-min auto-refresh; DB is already CST (no `AT TIME ZONE`); client-side Team pill filter (All/TM1-TM4) recomputes KPIs + medals — backend scope stays pinned to `TEAM-DFW` |
| Top Losses Lanes | `/reports/losses-lanes` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_budget_report_v4`; scope TEAM1-5 + TEAM-DFW / TMS,TMS3 / status D,P; excludes UNILINK & OILTEX; `margin_amt<0` filter on every visual; mirrors Bruno's Qlik sheet `de4ecec0-…/GjMvAnC`; presets MTD/Last Month/This Year/Custom; daily 7 AM CST weekly-movers email — **To**: emendoza + christian, **Cc**: jennifer + bkimbark, **Bcc**: msalazarm + dfrodriguez (single send, not fan-out; needs `RESEND_API_KEY` on Render) |
| OPs Margins | `/reports/ops-margins` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_budget_report_v4` (+ `mcleod_gld_movement` for carrier name on Negative Orders only); replaces Bruno's Qlik app `6cca7e6f-…`; richer cascading filter bar (Date / Division / Team / Company / Origin / Destination / Customer); 6 tabs (Margin by Customer / by Lane / Worst Lanes w/ 15-18-20% targets / Negative Orders / Negative Customers / Losses by Month+Week); always-on Trend (day/week/month) + Margin distribution histogram above the tabs; 8-week sparkline per customer in Margin by Customer; Pareto bar in Negative Customers; same scope as Losses Lanes (TEAM1-5+TEAM-DFW, TMS/TMS3, status D/P, excludes UNILINK & OILTEX); DFW sub-team filter (TM1-TM4) when Division=DFW; presets MTD/Last Month/This Year/Custom; **moves `d.sequence=1` from WHERE→ON** so orders older than the movement table's 45-day retention still show up; desktop-only (banner at <1280px); no daily email (covered elsewhere) |
| OPs Direct Compare | `/reports/ops-direct-compare` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_budget_report_v4`; replaces Bruno's Qlik app `4a8e2ffd-…`; **two independent panels (data1 vs data2)** each with its own Date / Division / Team / DFW sub-team filters; 6 KPIs per panel (Revenue / Profit / %Margin / #Loads / Avg $R/#L / Avg $P/#L) with center delta column (`data1 − data2`, green/red dots, computed client-side from the two panel-summary payloads); Top-5 Customer concentration pie + Customer & Lane detail tables per panel; Panel-2 tables include `Diff $Profit` & `Diff $Rev` columns (`data2 − data1`, Bruno's verbatim sign); always-on **last-12-months trend** ignores both panels' filters (cached 10-min in-process so every viewer shares one DB hit); Panel-2 also has `By-Customer Revenue & %Margin` combo + `Details by Order` table (this-year+last-year, ignores Panel-2 date filter, paginated 200/page); **diff tables computed in single SQL** via FULL OUTER JOIN of two CTEs (one DB hit per panel instead of four); same scope as OPs Margins (TEAM1-5+TEAM-DFW, TMS/TMS3, status D/P, excludes UNILINK & OILTEX); DFW sub-team filter (TM1-TM4) when Division=DFW; presets MTD / Last Month / YTD / Custom (defaults: Panel-1=MTD, Panel-2=Last Month); desktop-only (banner at <1280px); no daily email |
| Sales- Attrition to OPs | `/reports/sales-attrition-to-ops` | CEO, Executive, Sales, CORP, DFW, Operations, Finance | `mcleod_gld_budget_report_v4`; replaces Bruno's Qlik app `9b669acd-…`; per-customer attrition view: last-load date + days-since (color-banded green/amber/orange/red), #Loads / $Revenue / $Profit / %Margin filtered by Date/Teams/Customer; days-bucket pills (1-30 / 31-90 / 91-180 / 181-365 / 365+); 8-week #Loads sparkline per row; **fixed 13-month bar-chart strip** (#Loads/$Profit/%Margin) above the table that **ignores the Date filter** (Bruno's "It should not change with the date filter"); same scope as Losses Lanes (TEAM1-5+TEAM-DFW, TMS/TMS3, status D/P, excludes UNILINK & OILTEX); presets Last 365d/MTD/Last Month/YTD/Custom; trend endpoint cached 10 min; desktop-only banner <1280px; no daily email |
| Attrition WoW | `/reports/attrition-wow` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_budget_report_v4`; replaces Qlik app `e6440781-…`; same scope as Losses Lanes minus the `margin_amt<0` filter; **all windows are completed Mon-Sun ISO weeks**, current week excluded so KPIs don't bounce mid-week; tabs Overview / Reactive Customers / 12-Week Pivots / Weekly Trends; reactive tables segment customers by Days Since Last Load (1-7 / 8-28 / 29-63 / 64-248 / 249-365 / >365); WoW $Var = SUM(margin_amt) LW − LW-1; one-time Lifespan migration flips legacy Qlik row `4e326aa5-…` to custom_path. Desktop-only (banner at <1280px) |
| VoIP Calls Logs | `/reports/voip-calls-logs` | **everyone** (all 10 division TagRoles + admin) | `aivn_datalake_gold.public.vonage_gld_by_user` (1.06 GB, ~1.6M rows, fresh through current minute via existing upstream pipeline — **no n8n workflow involved**); replaces Bruno's Qlik `3e30136b-…`. Bruno's 5 visuals preserved (filter pills, detail table, pie, combo bar+line, hour-of-day line) plus 4 new panels (KPI strip, DOW × hour heatmap, Top 10 users by calls / by talk-time, hour-of-day rebuilt to span the **selected window** instead of one date). Single page (no tabs). Filter bar: Date pills (**WTD default** · Today · Last 7d · MTD · Last Month · YTD · Custom) · `call_direction` 3-pill (All/Inbound/Outbound/Intra-PBX) · free-text search across `username`/`calling_party`/`calling_party_identif`/`caller_id`/`dnis`/`call_details` (76k distinct caller IDs makes a dropdown unusable). Hard 2025-01-01 history floor server-side (matches Bruno's Qlik WHERE). Trend endpoint cached 60s in-process. Detail table paginated 200/page with sort + click-to-copy `call_id`. Backend gate is plain `require_user` (no role restriction). **Indexes added 2026-04-26 (concurrently)**: `idx_vonage_gld_by_user_start` + `idx_vonage_gld_by_user_start_dir` — without them every panel seq-scans 1 GB; with them WTD runs in ~30 ms. (Mob) sibling `9e477387-…` deleted. Desktop-only (banner at <1280px) |
| OPs Customer Score | `/reports/ops-customer-score` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_scorecard` (already refreshed by existing n8n — no new workflow); replaces Bruno's Qlik app `de4c1a28-…`; **4 tabs**: PU Overview / DEL Overview / PU Detail / DEL Detail. Single sticky filter bar (Division / DFW sub-team pill (TM1-TM4 in DFW) / Company TMS+TMS3 / Customer / Carrier (`payee_name`) / Date preset MTD-default · Last Month · YTD · Custom). On Overview tabs, the **This-Month / This-Quarter / This-Year KPI cards plus the Rolling-12-Months and Rolling-10-Weeks bar charts ignore the date filter** (snapshot view) — those panels are batched into one DB hit per side and **cached in-process for 10 min** keyed by (today, division, customer, carrier, company, sub_teams). Filter bar otherwise applies to all panels with `orig_actual_departure` (PU) or `dest_actual_departure` (DEL). Service-fail buckets: PU Our-Fault EDI ∈ (T4,T3,D1,D2,BO,BE,AL,AI,AH,AF,A5,A2) + stop_type ∈ ('','PU','SH'); PU Not-Our-Fault EDI ∈ (AD,AJ,AO,BQ,BT,C6,P2,S4,U2,U4) + stop_type ∈ ('','PU','SH') + orig_stop_type='PU'; DEL Our-Fault EDI ∈ (AL,D2,AZ,AH,BE,D1,A5,AI,AF,A2,A1,AU,U3) + stop_type ∈ ('','CO','SO'); DEL Not-Our-Fault EDI ∈ (C6,U4,U2,T7,P2,CA,RC,F1,BT,BQ,BJ,BH,BD,BC,BB,B8,B4,AX,AS,AR,AQ,AO,AN,AM,AJ,AG,AD,A6,A3) + stop_type ∈ ('','CO','SO'). Detail-tab Our-Fault / Not-Our-Fault tables paginated 200/page. `is_edi_servicefail` flag was audited and rejected — too broad (mixes PU+DEL). Desktop-only (banner at <1280px); no daily email. One-time Lifespan migration flips legacy Qlik row `de4c1a28-…` to custom_path |

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
15. **Code-Made Reports** — Non-Qlik reports via `report_type='custom'`; current: eSavings from Carriers, 2026 Official Budget Follow Up, XRay CORP Mng, CEO Executive, HR Access Doors, Podium Set DFW, Top Losses Lanes, Attrition WoW, OPs Margins, OPs Direct Compare, Sales- Attrition to OPs, OPs Customer Score, VoIP Calls Logs

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
SAVINGS_DATABASE_URL=<Aiven aivn_datalake_gold URL — powers ALL code-made reports (eSavings, Budget Follow Up, XRay CORP Mng, CEO Executive, HR Access Doors, Podium Set DFW, Top Losses Lanes, Attrition WoW, OPs Margins/Direct Compare/Customer Score, Sales-Attrition to OPs, VoIP Calls Logs)>
QLIK_TENANT_URL=https://mb01txe2h9rovgh.us.qlikcloud.com
QLIK_PRIVATE_KEY=<secret>
QLIK_ISSUER=https://analytics-hub.unilinkportal.com
QLIK_KEY_ID=analytics-hub-key-1
ALLOWED_ORIGINS=https://space.unilinkportal.com,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<secret>
TV_SECRET=<shared with frontend>
TIMEOFF_DATABASE_URL=<time-off DB for daily user sync>
RESEND_API_KEY=<shared with frontend — powers daily Losses Lanes weekly-movers email at 7 AM CST>
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
