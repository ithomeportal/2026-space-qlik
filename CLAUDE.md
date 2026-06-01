# UNILINK Space (Analytics Hub) — Role-Based Analytics Portal

> Detailed specs live in `docs/SPEC-*.md` (local only — fully gitignored).
> See [Spec Files](#spec-files) at the bottom for the index.
>
> **Qlik fully decommissioned 2026-05-28** — the portal now serves only
> code-made (custom) reports. Qlik embedding, the TV display, and all 36
> Qlik catalog rows were removed. (See `docs/SPEC-QLIK.md` for the archived
> integration notes.)

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
- Proxy passes non-JSON bodies (`text/csv`, future PDF/XLSX) through untouched — Content-Disposition is preserved so `<a href download>` works same-origin via the NextAuth session cookie. See `docs/SPEC-CODE-RULES.md` §31
- See `docs/SPEC-RELIABILITY.md` for the full cold-start + retry strategy

### Security (Non-Negotiable)
- NO hardcoded secrets — all via environment variables
- Rate limiting: 300 req/min standard, 10 req/min for token generation
- CSP allows: `cdn.jsdelivr.net`, `two026-space-qlik-back.onrender.com`, fonts.googleapis/gstatic (Qlik origins removed 2026-05-28)
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

### Code-Made Reports (cross-cutting — full detail in `docs/SPEC-CODE-RULES.md` + `docs/SPEC-CUSTOM-REPORTS.md`)
- ALL reports are now code-made. `reports.report_type` (always `'custom'`) + `reports.custom_path`; `/reports/[id]` redirects to `custom_path`
- **4-place mirror for every new report**: `CUSTOM_REPORTS` in `seed.py` · `REPORT_MAP` in `ReportIcons.tsx` · `<ReportGuard reportKey>` · backend `require_report_access("<key>")`. `role_report_access` is the single source of truth (admin UI `/admin/reports`)
- Endpoints under `/api/custom/<feature>/...`; external DBs get their own `asyncpg` pool + env var via `get_*_pool` in `routers/deps.py`
- Key SQL/code rules (SPEC-CODE-RULES §): no-TRIM sargability §1 · CST clock pin §2 · v4 sparseness §3 · date-decode clamp + NaN/Inf guards §4 · LATERAL first-match §5 · KPI=detail §16 · ratio-pivot numerator+denominator §33 · atomic wire-field rename §34 · per-user `user_id` scoping §35 · per-tab chart series §36 · grain toggle §37 · v4 profit = SUM(margin_amt), no total_charge≠0 filter (accessorials) §39 · direct-call endpoint shims must forward EVERY param (FastAPI `Query()` default isn't applied on a Python call → 500) §40 · Bonus Calculator display bracket % may intentionally ≠ payout money (gated sub-100-load weeks show the % but pay $0) — check LATEST bonus-spec changelog before "reconciling" §41 · `mcleod_gld_customer_windows` uses `orig_`/`dest_` prefix (NOT v4's `origin_`), join on `TRIM(UPPER(id))`, pre-aggregate into a CTE + hash join (no per-row LATERAL — no functional index on id), sentinel-guard >2000 §42
- Vestigial `qlik_app_id`/`qlik_sheet_id`/`use_classic` columns remain on `reports` (always NULL) — harmless; dropping them is tangled with boot-time DDL

### Backend keep-warm (Render free tier)
- Render spins the backend down after ~15 min idle (30-60s cold start → first page load shows empty reports; heavy endpoints like carriers-savings blow past the proxy's 45s abort → upstream-timeout alerts).
- **Primary keep-warm: self-hosted n8n workflow** "Keep-Warm — Space Analytics Backend (Render)" (id `aF3wH6ZpvDFEPXA5` on `n8n.unlk-repos.com`) — Schedule Trigger `*/5 * * * *` → HTTP GET `/api/health` (90s timeout, success-logs off). The n8n box is always-on, so unlike GitHub Actions it never drops cron slots. Set up 2026-06-01 after GH Actions `*/5` was found firing only ~20×/day with multi-hour overnight gaps (incident 2026-06-01 13:05 UTC).
- **Backstop: `.github/workflows/keepalive.yml`** (GH Actions `*/5`, best-effort — throttled/dropped, keep as redundancy only). The old Vercel cron (`vercel.json` → `/api/cron/keepalive`) was a no-op on Hobby (caps crons at once/day) and was **removed 2026-06-01** along with its route. See `docs/SPEC-RELIABILITY.md`

### Data, Seeding & TagRoles (full detail — `docs/SPEC-DATA.md` + `docs/SPEC-ADMIN.md`)
- Seed idempotent (`ON CONFLICT … DO UPDATE`); never `dict.pop()` module constants (use `.get()`); auto-seed when `role_report_access` empty; `seed_custom_reports(pool)` runs every startup so a new `CUSTOM_REPORTS` entry ships itself. Router order: search BEFORE reports
- Use bracket access `emp["name"]` for asyncpg Records, NOT `.get()`
- TagRoles **Title-Case** divisions; `admin`/`super_admin` lowercase; case-insensitive seed lookup; daily user sync 2 AM CST; NOT auto-assigned (manual per user). `POST /api/admin/dedupe-roles` merges case dupes

### Scheduled Jobs & Reliability (full detail — `docs/SPEC-RELIABILITY.md`)
- `daily_losses_alert` 07:00 CST (Resend); `daily_rfp_digest` 17:30 CST Mon-Fri (MS Graph, `admin-ms-api` app). Reuse `FONT_STACK`/`MONO_STACK` for HTML email (Outlook reset)
- Render free tier cold-starts 30–60s; **always-on n8n workflow `aF3wH6ZpvDFEPXA5` pings `/api/health` every 5 min** (primary keep-warm; GitHub Actions `keepalive.yml` is a best-effort backstop — the Vercel cron was removed 2026-06-01); proxy retries GET 5xx 3×, React Query 5×, skip 401/403; favicon backfill is a background task (never blocks lifespan)
- App favicons: tries `/icon.svg`→`/favicon.svg`→`/favicon.ico`→HTML `<link>`; stored as base64 data URIs in `icon_data`

---

## Features (1-line each — see spec files for details)

1. **Email Code Auth** — 8-digit code via Resend, NextAuth session
2. **3-Column Home** — TagRole filters | Reports | Apps, sorted by usage
3. **TagRole-Based Access** — Reports filtered by TagRole; Apps visible to all
4. **Inline Search** — DB-backed, title/description/note/tags, 300ms debounce
5. **Admin Console** — Reports/Apps/TagRoles/Users CRUD + matrix view (report rows are code-seeded; admin manages access/metadata, not creation)
6. **Apps (External Links)** — Favicon-iconed links, visible to all users
7. **Daily User Sync** — APScheduler from People Management DB at 2 AM CST
8. **User Access Matrix** — `/admin/users/[id]` report × TagRole matrix
9. **Keep-Alive** — self-hosted n8n (`n8n.unlk-repos.com`, always-on) pings `/api/health` every 5 min (primary, reliable); GitHub Actions `keepalive.yml` is a redundant backstop
10. **Code-Made Reports** — All reports are `report_type='custom'` Next.js routes. Current catalog: eSavings from Carriers, 2026 Official Budget Follow Up, XRay CORP Mng, XRay DFW Mng, XRay DFW TM1..TM4, CEO Executive, HR Access Doors, DFW Access Doors, Admin Access Doors, Podium Set DFW, DFW Podium Top, Top Losses Lanes, Attrition WoW, OPs Margins, OPs Direct Compare, Sales- Attrition to OPs, OPs Customer Score, VoIP Calls Logs, Track Award Loads, Performance for RFPs, Risk Asss for Carriers, IT Tickets Mgmt, Admin Aging Cashflow, Ops Portal - Overview, KAM Performance - DFW, Bonus Calculator, Reports Index, CEO Cockpit, Carrier SMS Score. **Full per-report spec in `docs/SPEC-CUSTOM-REPORTS.md`.**

> **CEO Cockpit** (`ceo-cockpit`, 2026-05-29) is an *aggregator*, not a data report: its `/api/custom/ceo-cockpit/summary` fans out in-process (httpx `ASGITransport`) to ~19 existing report KPI endpoints and renders one RAG-coloured hero KPI per report, click-through to the source. Pure `TILES` config in `routers/ceo_cockpit.py` (no own SQL), personalized by per-tile self-gating. See `docs/SPEC-CUSTOM-REPORTS.md` §31.

> _Removed 2026-05-28 (Qlik decommission): Viewer-Only Embed, Full-Page Qlik Embed, Classic Embed Mode, TV Display (`/dfw-podium`), Responsive `(Mob)` Qlik reports._

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) on Vercel |
| Styling | Tailwind CSS + shadcn/ui |
| State | React Query (TanStack) |
| Backend | FastAPI (Python) on Render |
| Auth | NextAuth.js v5 beta-30 (Resend, JWT strategy) |
| Scheduler | APScheduler (daily user sync + email digests) + GitHub Actions (keep-alive, every 5 min) |
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
    reports/[id]/page.tsx        # Redirects to the report's custom_path
    reports/<custom>/page.tsx    # Code-made report (one folder per report)
    admin/
      layout.tsx                 # Admin sidebar
      page.tsx                   # Usage analytics
      reports/page.tsx           # Report metadata + TagRole assignment (no creation)
      apps/page.tsx              # App CRUD
      roles/page.tsx             # TagRole CRUD
      users/page.tsx             # User list
      users/[id]/page.tsx        # User detail + access matrix
    api/auth/[...nextauth]/      # NextAuth handlers
    api/proxy/[...path]/route.ts # Backend proxy w/ retry logic
    (auth)/login/page.tsx
  components/
    SearchBar.tsx
    ReportGrid.tsx
    ReportCard.tsx
    ReportGuard.tsx              # role_report_access gate
    Providers.tsx                # React Query w/ 5× retry, skip 401/403
  lib/
    auth.ts
    api.ts
    use-is-mobile.ts
    use-debounce.ts
  next.config.mjs                # CSP headers
.github/workflows/keepalive.yml  # Backstop keep-warm: pings /api/health every 5 min (primary is n8n aF3wH6ZpvDFEPXA5)

backend/
  app/
    main.py                      # FastAPI, CORS, lifespan, APScheduler
    config.py                    # Pydantic Settings
    clock.py                     # cst_today() + _set_cst_session pool init
    routers/
      deps.py                    # require_user / require_admin / require_report_access / pool factories
      reports.py                 # /api/reports, /api/apps
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
```
> Removed 2026-05-28: `NEXT_PUBLIC_QLIK_TENANT`, `TV_SECRET` (Qlik decommission).

### Backend (Render)
```
DATABASE_URL=<Aiven Postgres URL — analytics_hub>
SAVINGS_DATABASE_URL=<Aiven aivn_datalake_gold URL — most code-made reports>
AUTOMATIONS_DATABASE_URL=<Aiven automations_db URL — Track Award Loads, Performance for RFPs>
FRESHSERVICE_DATABASE_URL=<Aiven fresh_services_unlk URL — IT Tickets Mgmt; percent-encode $ → %24>
AP_DATABASE_URL=<Aiven unilink_portal_ap (read-only role) — Carrier SMS Score (carriers ⨝ fmcsa_sms_data); percent-encode $ → %24>
FINANCIAL_DATABASE_URL=<UNLK-Financial DB (read-only) — exchange_rates (Banxico FIX=DOF); OPTIONAL, only prefills Bonus Calculator FX suggestion; percent-encode $ → %24>
TIMEOFF_DATABASE_URL=<time-off DB for daily user sync>
ALLOWED_ORIGINS=https://space.unilinkportal.com,https://2026-space-qlik-front.vercel.app
SEED_SECRET=<secret>
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
> Removed 2026-05-28: `QLIK_TENANT_URL`, `QLIK_PRIVATE_KEY`, `QLIK_ISSUER`, `QLIK_KEY_ID`, `TV_SECRET` (Qlik decommission). These can be deleted from the Render dashboard — the code no longer reads them (leaving them is harmless).

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
- **Admins** — dfrodriguez, kmeneses, msalazarm, dcastrog (admin role auto-assigned)
- **Single source of truth** — `role_report_access` table (admin UI at `/admin/reports`); both `<ReportGuard>` and backend `require_report_access(...)` read it. See `docs/SPEC-CODE-RULES.md` §15

---

## Qlik Tenant — DECOMMISSIONED 2026-05-28

Qlik is no longer connected to this app. The tenant
(`mb01txe2h9rovgh.us.qlikcloud.com`) and its apps still exist in Qlik Cloud
but the portal no longer embeds, authenticates to, or references them. Archived
tenant/IdP/app details are in `docs/SPEC-QLIK.md` + `docs/SPEC-QLIK-INVENTORY.md`.

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
| `docs/SPEC-QLIK.md` | **ARCHIVED (Qlik decommissioned 2026-05-28)** — embed, JWT, IdP, TV display, lessons learned |
| `docs/SPEC-QLIK-INVENTORY.md` | **ARCHIVED** — historical Qlik app inventory with IDs, sheets, categories |
| `docs/SPEC-DATA.md` | PostgreSQL schema, API endpoints |
| `docs/SPEC-SEARCH.md` | Search engine, PostgreSQL ILIKE |
| `docs/SPEC-ADMIN.md` | Admin console, TagRoles, user sync, apps |
| `docs/SPEC-RELIABILITY.md` | Cold starts, proxy retry, keep-alive, scheduled jobs, incidents |
| `docs/SPEC-ROADMAP.md` | Phased delivery, success metrics, lessons learned |
| `docs/SPEC-CUSTOM-REPORTS.md` | Code-made (non-Qlik) reports — full per-report spec + checklist |
| `docs/SPEC-CODE-RULES.md` | Cross-cutting code rules (sargability, CST clock, asyncpg, Render env, Outlook fonts, etc.) |
| `docs/SPEC-RFP-DAILY-DIGEST.md` | RFP Performance daily email digest details |
| `docs/SPEC-BONUS-CALCULATOR.md` | Bonus Calculator (CEO+HR) — engine port, live-datalake feed, 6th→6th period, HR-pinned FX, roster |
