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
| 2026 Official Budget Follow Up | `/reports/budget-followup-2026` | CEO, Executive, Operations, Finance, CORP, DFW | `daily_production_budget_report` + v4 team map. **Bruno feedback round 1 (2026-04-28)**: Range presets `Full 2026 / YTD / MTD / Custom` (MTD = 1st-of-month → today). Monthly chart + Last-12-Weeks chart (ISO Mon-Sun, current excluded). 5 leaderboard cards between By-Team and By-Customer (Top/Worst Volume + Top/Worst Profit `where budget>0` + Non-Budget Active `where profit_budget=0 AND profit_actual>0`). Trajectory tabs use **Mon-Fri working days, no holidays** (`_count_workdays`) for AVG×LastMonth divisor + Projected days-remaining; numerator sums stay calendar-day. AVG×Week=/3, AVG×Day=/14. Avg+Projected always anchor to *now*, ignore Range filter. **Bruno feedback round 2 (2026-04-30)**: KPI strip is now 5 cards in this exact order — `Active Days · Pending Days · Days Elapsed · Days Remaining · Holidays Days`. Days Elapsed/Remaining now respect the filter window (was full year). Pending Days = Mon-Fri non-holiday workdays remaining (today→window-end). Holidays Days = US federal holidays in the window. **Active Customers KPI removed** from the strip. `US_HOLIDAYS_2026` constant in `budget_followup.py` is the single source of truth for holiday math (also used by `_count_workdays`). Monthly chart is **pinned to full year 2026** (frontend passes `YEAR_START..YEAR_END` regardless of Date filter). Both Monthly + Weekly bars now show **two value labels per column** (Actual on top, Budget below). Each By-Team card replaces "Rev variance" with **Load variance + Profit variance**. **By-Customer Overview** column order is now Budget → Actual → Var for every metric group: `Loads B/A/Var · Revenue B/A/Var · Profit B/A/Var · Margin B/A/Var`; new **Margin Var** column = `margin_actual_pct − margin_budget_pct` (pp, computed client-side). **Loads tab restored** (Overview / Revenue / Profit / Loads). In Revenue/Profit/Loads tabs: first three columns reordered to Budget → Actual → Var with **cream-tint background** (`bg-[#FEF7E6]`); column "AVG × Last Month" renamed to **"AVG per day Last Month"**; Projected font is green if >0, red if <0; sticky **Totals row at top** of each detail table sums every numeric column over the displayed rows. |
| XRay CORP Mng | `/reports/xray-corp-mng` | CEO, Executive, CORP, Operations, Finance | v4 + scorecard + movement + budget_report + savings |
| CEO Executive | `/reports/ceo-executive` | **admin + CEO only** | `_production_cte` UNIONs `daily_production_budget_report` (CORP) with v4-DFW for Overview roll-ups; detail tabs read v4. Perf indexes: `idx_v4_dep`, `idx_movement_order_company_mv`. See SPEC-CUSTOM-REPORTS.md |
| Podium Set DFW | `/reports/podium-dfw` | admin + DFW | `mcleod_gld_order_post_hist` ⨝ v4; replaces Qlik `0a0c7a49-…`; 15-min auto-refresh; client-side Team pill filter. **Bruno feedback round 1 (2026-04-30, commit `5a3b11d`)**: added 5 podium leaderboards between KPI strip and detail table — **This Week (Mon-Sun)** Top-3 by Profit / Margin / Loads + **Today** Top-3 by Loads / Profit. Single round-trip `/podiums` endpoint with 5 `json_agg` subqueries on `weekly`/`daily` CTEs. Margin uses `WHERE revenue>0`. **Totals row sums only the 3 displayed rows** (Bruno Q1, NOT full universe — the PDF mock's 187 was misleading); Margin total = ΣProfit/ΣRevenue across the 3. Mon-Sun via `date_trunc('week', CURRENT_DATE)` (Postgres ISO Mon) + half-open `+ 7`. Cream-tint sticky Totals at top, medals 🥇🥈🥉 in lead column |
| Top Losses Lanes | `/reports/losses-lanes` | CEO, Executive, CORP, DFW, Operations, Finance | v4; scope TEAM1-5 + TEAM-DFW / TMS,TMS3 / status D,P; excludes UNILINK + OILTEX; `margin_amt<0`; daily 7 AM CST weekly-movers email |
| OPs Margins | `/reports/ops-margins` | CEO, Executive, CORP, DFW, Operations, Finance | v4 (+ movement for carrier name); 6 tabs; always-on Trend + Margin histogram; same scope as Losses Lanes |
| OPs Direct Compare | `/reports/ops-direct-compare` | CEO, Executive, CORP, DFW, Operations, Finance | v4; two independent data1/data2 panels with center delta; cached 12-month trend; same scope as OPs Margins |
| Sales- Attrition to OPs | `/reports/sales-attrition-to-ops` | CEO, Executive, Sales, CORP, DFW, Operations, Finance | v4; per-customer attrition w/ days-since color band; fixed 13-month strip ignores Date filter |
| Attrition WoW | `/reports/attrition-wow` | CEO, Executive, Sales, CORP, DFW, Operations, Finance | v4; ISO Mon-Sun weeks (current excluded); **3 tabs (post-Bruno 2026-04-27)**: Overview · Reactive Customers · Trends & Pivots (merged). Cream-bg L8W avg col; integer AVG LOADS; by-Customer pivot has red/yellow/green status dot vs 8w avg; Trends bars use panel color above-avg, gray below. Reactive bucket order: 2-4W before LW |
| VoIP Calls Logs | `/reports/voip-calls-logs` | **everyone** | `vonage_gld_by_user` (1 GB, ~1.6M rows, fresh through current minute, no n8n); WTD default; indexes `idx_vonage_gld_by_user_start{,_dir}` |
| OPs Customer Score | `/reports/ops-customer-score` | CEO, Executive, CORP, DFW, Operations, Finance | `mcleod_gld_scorecard`; 4 tabs (PU/DEL × Overview/Detail); KPI cards + 12mo/10wk charts ignore Date filter and cache 10 min. **Bruno feedback round 1 (2026-04-30, commit `60d547e`)**: CORP sub-team pills (TEAM1-5) mirror the DFW sub-team UX (`?corp=` URL key, threads through existing backend `teams` param); compact 4-card top KPI strip on PU+DEL Overview (Month/Qtr/Year + filtered Service-Fail KPI all on one `lg:grid-cols-4` row); Team & Customer tables side-by-side with 380px scroll cap; Rolling 12mo + 10wk charts replaced with Recharts `<ComposedChart>` (red Service-Fail bars left axis + colored % On Time line right axis 0-100, `<LabelList position="top">` keeps per-bar counts visible). Backend untouched — all UI changes. Full spec: SPEC-CUSTOM-REPORTS.md §18.7 |
| Track Award Loads | `/reports/track-award-loads` | CEO, Executive, Sales, Procurement, Operations, Finance, CORP, DFW | `contract_performance_analysis` in **`automations_db`** (NOT `aivn_datalake_gold` — own pool, `AUTOMATIONS_DATABASE_URL` env var) ⨝ `awards_tracker_registration_source` (per-lane RPM/Min Chg/All-in rates via natural-key LEFT JOIN). Replaces legacy Qlik `949cafc8-…` (unilink.us tenant — not embeddable). n8n daily 02:25 (`3XkU4PfCm4EBYgTl Contract Performance Analysis`) keeps 15-day rolling window; **always pin to `analysis_date = MAX` snapshot** or aggregates inflate by ~15×. 4 filter pills · 4 KPI containers · 4 detail tables. Partial index `idx_cpa_primary_latest` covers the snapshot+filter path. Days-to-Exp red banner + WoW Δ on Total Actual Volume (joins natural key — destination `audit_id` is SERIAL, not stable across snapshots) |
| Performance for RFPs | `/reports/rfp-performance` | CEO, Executive, Sales, Procurement, CORP, DFW, Operations, Finance | `rfp_results_history` in **`automations_db`** (n8n workflow `Pgpg097swOFyjFT9`, daily 01:00 CST — already excludes test customer 59 + inactive RFPs, latest active round per RFP). Replaces legacy Qlik `6df25048-…`. Filter pills: Date / Division / Department / Bussiness Type / Customer / Type / Status (default Date = YTD). KPI blocks: Potential Revenue grand total + Open / Closed / Lost / Won (Won block adds Lane/Load/Awarded ratios). Convertio Ratio sensitivity table (0.5%–5%, current calendar year, dynamic — replaces Bruno's hardcoded 2026). Two combo charts (Volume Awarded, Revenue Awarded — last 12 mo, ignore Date filter). Tabbed Summary by Operations / Sales / Division. Potential Revenue Per Month (full history, ignore Date). Tabbed Customer Summary + Convertio detail. Paginated RFP Details. **Conv = Awarded / Potential W/O** (Bruno's quirky definition — preserved verbatim). **Lane Awarded Ratio % denominator = no_lanes WHERE status='Won'**, **Awarded Convertio Ratio denominator = grand-total potential_revenue** (no status filter — explicit in the PDF). Recommended indexes (avnadmin): `(submitted_date)`, `(status, submitted_date)`, `(customer_name)`. |
| HR Access Log Doors | `/reports/hr-access-doors` | CEO, Executive, HR, IT | `zk_gld_onlyfingerprint` ⨝ `timeoff_employee`; first-punch/day, expected-arrival rule per dept+job_title; integer minute delta. Replaces Bruno's legacy Qlik `4573ff42-…` (unilink.us tenant). |
| Risk Asss for Carriers | `/reports/carrier-risk` | CEO, Executive, Procurement, CORP, DFW, Operations, Finance | `mcleod_gld_dispatchers` ⨝ `mcleod_gld_budget_report_v4` (revenue/profit only). **First portal report on dispatchers**. **`carrier_cost = override_pay_amt + driver_extra_pay`** — verified against Bruno's $1,372 grand-total avg (matches to $1,371.84). Do NOT use `b.total_carrier_pay` ($1,485 avg, wrong). 4 filter pills (Date / Lane / Customer / Team) · 6 KPI cards (last one = % single-carrier lanes + % volume in single-carrier lanes) · 3 panels: by-Lane (#Carrier / #Mov / Avg Cost + Top1 share / HHI / Cost CV / % Margin / red-amber-green risk band) · by-Carrier+Lane · order-level Details. Server-side pagination + sort. Dispatchers PK is `(movement_id, id, company_id)` — useless for date queries; recommended index on `(origin_actual_departure)` (avnadmin DDL only). Replaces Qlik `d7b9deb0-…` (legacy unilink.us tenant — not embeddable). |
| IT Tickets Mgmt | `/reports/it-tickets-mgmt` | **everyone** | `fresh_services_unlk."Tickets" ⨝ "Agents"` (own pool, `FRESHSERVICE_DATABASE_URL`, fed by an external Spark ETL — **NOT n8n**). **First portal report on FreshService data**. Replaces Qlik `86da731f-…` (sheets `RqXzx` Incidents + `8aae69c7-…` Service Request) — single page with **Type tabs** (Service Request / Incident) so the two near-identical Qlik sheets share one filter/KPI surface. Default `Last 30d` (Today / WTD / Last 7d / Last 30d / MTD / Last Month / YTD / Custom). KPIs: Pending Now / % Open / Closed / % Closed; charts: Pending-by-Month (last 12 mo, ignores filter), Status & Priority donuts, Pending-by-Week, Pending-by-Day, Agents-Assignments, History (Status/Category sub-tabs). Detail tables: Pending (oldest first, aging color band 0–3d / 4–7d / 8–14d / >14d) and Closed (newest UpdatedDate first), server-side paginated + sortable. **Bruno's PDF SQL has a JOIN bug** — `LEFT JOIN Agents a ON t.Id = a.Id` matches **0 rows** (ticket Ids 17xxx vs agent Ids 21000xxx); corrected to `ON t."ResponderId" = a."Id"` (15,647 matches). **Status code mapping** mirrored: `'6'`→`In Progress`, `'8'`→`Waiting for user response`. Excludes Onboarding/Offboarding/Cancelled/Canceled/Test (IT) categories and any subject ILIKE `%test%` (Bruno's domain rules). Indexes added 2026-04-28 via avnadmin: `idx_tickets_created`, `idx_tickets_type_status_active` (partial), `idx_tickets_responder`, `idx_tickets_updated`. |
| DFW Access Log Doors | `/reports/dfw-access-doors` | DFW, DFW-Assistent, DFW KAM, Assitent OPs manager | Department-locked clone of HR Access Log Doors — server-side gate `dep = 'Operations (DFW)'` (not a query param, can't be widened); imports SQL fragments from `hr_access_doors.py` (single source of truth for the on-time rule); replaces by-department bar with by-job-title bar; 30-day trend also locked to Operations (DFW). |
| Admin Aging Cashflow | `/reports/admin-cashflow` | CEO, Executive, Finance, CORP, DFW, Operations, AdminFinance | `mcleod_gld_cashflow` (Spark ETL — already in datalake, no n8n). Replaces Bruno's legacy Admin CashFlow Qlik dashboard. **First portal report on `mcleod_gld_cashflow`** — column widths mirror v4 (team_id varchar(8), company_id varchar(4), status varchar(1), ready_to_bill varchar(512)) so the same `_pad_variants` pattern applies. Default `MTD` (Today / WTD / Last 7d / MTD / Last Month / YTD / Custom). 5 filter pills (Date / Team / Company / Customer / Contract Type). Top KPI strip (5): 3 discipline % (Delivery≤10d / BOL≤2d / CarrInv≤2d) each with 12-week sparkline + green/amber/red threshold band, plus Delivered-not-billed $ + Ready-not-billed $ (warn-tinted >$1M). Aging-buckets bar chart (0-3 / 4-7 / 8-10 / 11-15 / >15). Top-delayed-customers leaderboard ($ revenue at risk where bill-to-delivery >10d). Banner when Delivered+Ready unbilled total > $3M. 2 unbilled tables (paginated, oldest-delivered-first / oldest-shipped-first). Aging detail in 3 tabs (Delivery vs Bill / BOL vs Bill / CarrInv vs Bill (C-B)) with sub-KPI cards (≤threshold / >threshold counts) and Days color-band column. **Bug fixes vs Bruno's PDF (verified with user 2026-04-30)**: real calendar-day diff `(a::date - b::date)` everywhere — Bruno's Qlik `day(a) - day(b)` only returned day-of-month and silently broke Apr-30→May-2 (computed -28 instead of 2); "Delivery vs Bill" detail uses `dest_actual_arrival > '2000'` (delivered) not the PDF typo `< '2000'`; "CarrInv vs Bill" direction = `invoice_recv_date - bill_date` (matches "C-B" card title and PDF page-6 detail-table); "Orig Sched Early" column = `orig_orig_sched_early` (raw pickup window early). Indexes added 2026-04-30 via avnadmin: `idx_cashflow_arrival(origin_actual_arrival)`, `idx_cashflow_bill_date(bill_date)`, `idx_cashflow_unbilled(status, ready_to_bill, origin_actual_arrival) WHERE bill_date < '2000-01-01'`. |

### TagRole Canonicalization (see `docs/SPEC-ADMIN.md`)
- Canonical form: **Title-Case** for divisions (CEO, Executive, CORP, DFW, Finance, HR, IT, Operations, Procurement, Sales)
- `admin` and `super_admin` stay lowercase (singletons)
- Seed uses `role_ids_ci` (lowercased-key dict) for case-insensitive lookup
- `POST /api/admin/dedupe-roles?secret=<SEED_SECRET>` merges case duplicates and migrates all refs

### Render Env Vars — Always URL-Encode `$` in Connection Strings
- Render silently strips one `$` from values containing `$$` during env-var injection (length on dashboard ≠ length in container — verified 2026-04-28 with `FRESHSERVICE_DATABASE_URL`: dashboard 121 chars, container 120). Auth fails with no log, pool stays None, endpoint 503s, frontend spins forever
- **Always percent-encode special chars in DB URLs**: `$` → `%24`, `*` → `%2A`, `@` → `%40`, `#` → `%23`, `?` → `%3F`. asyncpg accepts encoded URLs identically to raw ones — no downside
- After setting an env var via `PUT /v1/services/{id}/env-vars/{KEY}`, hit `GET /api/_pool_diag` (or any endpoint that exercises the pool) on the next deploy and confirm `fs_url_len` matches the encoded length you sent

### Scheduled Email Digests (see `docs/SPEC-RELIABILITY.md` §Scheduled Jobs)
- **`daily_losses_alert`** — 07:00 CST daily, Resend → `noreply@unilinkportal.com`, Top Losses Lanes weekly-movers (`app/services/losses_alerts.py`).
- **`daily_rfp_digest`** — 17:30 CST Mon-Fri, **MS Graph** → `ithome@unilinktransportation.com`, RFP Performance summary (`app/services/rfp_daily_digest.py`). Recipients hard-coded in `_scheduled_rfp_digest()` in `main.py:46-71`. Uses the existing `admin-ms-api` Entra app (Mail.Send Application perm + admin consent). Token POST is hand-rolled in `app/services/msgraph_mailer.py` — **no `msal` dep** (httpx is enough). Test endpoint: `POST /api/admin/rfp-digest/test?secret=$SEED_SECRET&to=...&cc=...&bcc=...`.
- Adding a new digest: copy `rfp_daily_digest.py` shape (data-fetch via existing pool + `render_html` + `send_mail`), register a new `_scheduled_*` wrapper in `main.py` lifespan, document in SPEC-RELIABILITY.md table.

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
15. **Code-Made Reports** — Non-Qlik reports via `report_type='custom'`; current: eSavings from Carriers, 2026 Official Budget Follow Up, XRay CORP Mng, CEO Executive, HR Access Doors, DFW Access Doors, Podium Set DFW, Top Losses Lanes, Attrition WoW, OPs Margins, OPs Direct Compare, Sales- Attrition to OPs, OPs Customer Score, VoIP Calls Logs, Track Award Loads, Performance for RFPs, Risk Asss for Carriers, IT Tickets Mgmt, Admin Aging Cashflow

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
AUTOMATIONS_DATABASE_URL=<Aiven automations_db URL — powers Track Award Loads (n8n's contract_performance_analysis) and Performance for RFPs (n8n's rfp_results_history). Same Aiven cluster as SAVINGS_DATABASE_URL, just dbname=automations_db. Use the same read-only role you use for SAVINGS_DATABASE_URL — do NOT bake avnadmin in here.>
FRESHSERVICE_DATABASE_URL=<Aiven fresh_services_unlk URL — powers IT Tickets Mgmt (Tickets/Agents tables fed by an external Spark ETL, NOT n8n). Same Aiven cluster as SAVINGS_DATABASE_URL, just dbname=fresh_services_unlk. Use the same read-only role you use for SAVINGS_DATABASE_URL — do NOT bake avnadmin in here. **Percent-encode `$` → `%24` and `*` → `%2A` in the password** (Render strips one `$` from `$$` during env-var injection — silently breaks auth).>
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
# Microsoft Graph (admin-ms-api app) — powers RFP Performance daily digest at 5:30 PM CST Mon-Fri
# from ithome@unilinktransportation.com. Same Entra app as /BOT/admin-ms; needs Mail.Send Application permission with admin consent.
MS_TENANT_ID=<Unilink Entra tenant id, same as /BOT/admin-ms>
MS_CLIENT_ID=<admin-ms-api client id>
MS_CLIENT_SECRET=<admin-ms-api secret — expires 2027-12-30>
MS_SEND_FROM=ithome@unilinktransportation.com
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
