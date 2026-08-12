import asyncio
import logging
import time
from contextlib import asynccontextmanager

import asyncpg
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.services.keepwarm_monitor import classify_keepwarm_source
from app.routers import (
    admin,
    admin_cashflow,
    attrition_wow,
    bonus_calculator,
    booker_scorecard,
    budget_followup,
    carrier_risk,
    carrier_sms,
    carriers_savings,
    ceo_cockpit,
    ceo_executive,
    dfw_losses,
    hd_spot,
    hr_access_doors,
    it_tickets,
    kam_performance_dfw,
    losses_lanes,
    ops_customer_score,
    ops_customer_score_team,
    ops_direct_compare,
    ops_direct_compare_team,
    ops_margins,
    ops_portal_overview,
    ops_portal_overview_team,
    ops_team_perf_digest,
    podium_dfw,
    podium_top,
    preferences,
    reports,
    reports_index,
    rfp_performance,
    sales_attrition_to_ops,
    scoped_access_doors,
    search,
    track_award_loads,
    voip_calls,
    xray_corp,
    xray_dfw,
    xray_dfw_team,
)

logger = logging.getLogger(__name__)


async def _scheduled_user_sync():
    """Background job: sync users from time-off DB."""
    try:
        from app.services.sync_users import sync_users

        result = await sync_users()
        logger.info(f"Scheduled user sync complete: {result}")
    except Exception as e:
        logger.error(f"Scheduled user sync failed: {e}")


async def _scheduled_losses_alert():
    """Background job: send daily 7 AM CST Losses Lanes weekly-movers email."""
    try:
        pool = getattr(app.state, "savings_pool", None)
        from app.services.losses_alerts import send_weekly_movers_email

        result = await send_weekly_movers_email(pool)
        logger.info(f"Scheduled losses alert complete: {result}")
    except Exception as e:
        logger.error(f"Scheduled losses alert failed: {e}")


async def _scheduled_bonus_history_finalize():
    """Background job: freeze closed Bonus-Calculator months into bonus_history.

    Idempotent + self-backfilling — only writes a period once its cutoff (6th of
    the next month 23:59 CST) has passed and it isn't already stored.
    """
    try:
        from app.services.bonus_history import finalize_due_periods

        result = await finalize_due_periods(app)
        logger.info(f"Scheduled bonus history finalize complete: {result}")
    except Exception as e:
        logger.error(f"Scheduled bonus history finalize failed: {e}")


async def _scheduled_rfp_digest():
    """Background job: send daily 5:30 PM CST RFP Performance email digest.

    Recipients confirmed by Diego on 2026-04-30:
        To:  pricing@unilinktransportation.com
        Cc:  emendoza (CEO), janaya
        Bcc: dfrodriguez, msalazarm
    """
    try:
        pool = getattr(app.state, "automations_pool", None)
        from app.services.rfp_daily_digest import send_daily_digest

        result = await send_daily_digest(
            pool,
            to=["pricing@unilinktransportation.com"],
            cc=[
                "emendoza@unilinktransportation.com",
                "janaya@unilinktransportation.com",
            ],
            bcc=[
                "dfrodriguez@unilinktransportation.com",
                "msalazarm@unilinktransportation.com",
            ],
        )
        logger.info(f"Scheduled RFP digest complete: {result}")
    except Exception as e:
        logger.error(f"Scheduled RFP digest failed: {e}")


async def _scheduled_ops_team_digest():
    """Background job: email the Ops Portal "Team" (Team Monthly Performance)
    panel to janaya@ twice daily at 06:00 and 18:00 CST (Bruno R9, 2026-07-01).

    Data is read in-process from the exact /team-performance-by-team endpoint,
    so the email always matches the report. Log-and-swallow."""
    try:
        from app.services.ops_team_digest import send_team_digest

        result = await send_team_digest(
            app,
            to=["janaya@unilinktransportation.com"],
        )
        logger.info(f"Scheduled ops team digest complete: {result}")
    except Exception as e:
        logger.error(f"Scheduled ops team digest failed: {e}")


async def _scheduled_lane_rates_prewarm():
    """Background job: pre-warm SONAR + 123LB monthly rates for lanes in the
    current and previous month so the eSavings report never blocks on a cold
    cache. Runs daily at 5 AM CST."""
    try:
        pool = getattr(app.state, "savings_pool", None)
        from app.services.lane_rates_prewarm import prewarm_lane_market_rates

        result = await prewarm_lane_market_rates(pool)
        logger.info(f"Lane-rates prewarm complete: {result}")
    except Exception as e:
        logger.error(f"Lane-rates prewarm failed: {e}")


async def _scheduled_scorecard_mirror_check():
    """Background job: daily freshness watchdog for the portal-owned
    mcleod_gld_scorecard_portal mirror.

    The portal reads an n8n-maintained TRUNCATE+load mirror (can't bloat), so the
    health signal flipped from "bloated?" to "fresh?". Emails Diego if the n8n
    refresh has stalled (source advanced but mirror didn't catch up) or the
    mirror is missing/empty. SELECT-only. See
    app/services/scorecard_mirror_monitor.py.
    """
    try:
        pool = getattr(app.state, "savings_pool", None)
        from app.services.scorecard_mirror_monitor import check_scorecard_mirror

        result = await check_scorecard_mirror(pool)
        logger.info(f"Scorecard mirror check complete: {result}")
    except Exception as e:
        logger.error(f"Scorecard mirror check failed: {e}")


async def _scheduled_keepwarm_check():
    """Background job: daily watchdog for the two keep-warm pingers.

    /api/health stamps a row per pinger in ``keepwarm_pings``; this checks both
    are still beating and emails Diego if one has stalled. It exists because the
    n8n primary (aF3wH6ZpvDFEPXA5) has no failure visibility of its own — a
    silent stop would otherwise surface nowhere until users saw blank reports.
    See app/services/keepwarm_monitor.py.
    """
    try:
        pool = getattr(app.state, "pool", None)
        from app.services.keepwarm_monitor import check_keepwarm

        result = await check_keepwarm(pool)
        logger.info(f"Keep-warm check complete: {result}")
    except Exception as e:
        logger.error(f"Keep-warm check failed: {e}")


async def _scheduled_datalake_warmup():
    """Keep the aivn_datalake_gold shared buffers hot.

    The keep-warm pings only hit ``/api/health`` (no DB), so they wake the
    Render dyno but leave the datalake's Postgres page cache cold — the first
    real user hit on a heavy report then pays a 20-28s cold-scan penalty
    (especially when an external McLeod->gold bulk load has evicted our hot
    pages). This job runs the heaviest ops-portal-overview queries in-process
    every 5 min so those tables' index/heap pages stay resident, turning the
    user's first hit from ~25s into ~1-5s. Best-effort: log-and-swallow.
    """
    pool = getattr(app.state, "savings_pool", None)
    if pool is None:
        return
    # Synthetic admin header — admin bypasses require_report_access (deps.py),
    # so the warmup runs the exact same SQL real users trigger.
    auth = 'Bearer {"sub":"warmup","email":"warmup@internal","name":"warmup","roles":["admin"]}'
    # In-process via ASGITransport, but require_user cannot tell that apart from a
    # network call — so the internal callers must carry the proxy secret too.
    internal_headers = {"authorization": auth}
    if settings.PROXY_SHARED_SECRET:
        internal_headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    endpoints = (
        "/api/custom/ops-portal-overview/actuals",
        "/api/custom/ops-portal-overview/service",
        "/api/custom/ops-portal-overview/by-order",
    )
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://warmup.internal", timeout=60.0,
        ) as client:
            results = await asyncio.gather(
                *[client.get(ep, headers=internal_headers) for ep in endpoints],
                return_exceptions=True,
            )
        ok = sum(1 for r in results if not isinstance(r, Exception) and r.status_code == 200)
        logger.info(f"Datalake warmup: {ok}/{len(endpoints)} endpoints hot")
    except Exception as e:
        logger.warning(f"Datalake warmup failed: {e}")


async def _backfill_favicons(pool: asyncpg.Pool):
    """Background task: backfill missing favicons without blocking startup."""
    try:
        apps_without_icons = await pool.fetch(
            """SELECT id, url FROM apps
               WHERE is_active = TRUE
                 AND (icon_data IS NULL
                      OR icon_data LIKE 'data:image/png;base64,%')"""
        )
        if not apps_without_icons:
            return
        logger.info(f"Backfilling favicons for {len(apps_without_icons)} apps (background)...")
        from app.routers.admin import _fetch_favicon

        for row in apps_without_icons:
            try:
                icon_data = await _fetch_favicon(row["url"])
                if icon_data:
                    await pool.execute(
                        "UPDATE apps SET icon_data = $1 WHERE id = $2",
                        icon_data,
                        row["id"],
                    )
                    logger.info(f"Favicon backfilled for app {row['id']}")
            except Exception as e:
                logger.warning(f"Favicon backfill failed for {row['url']}: {e}")
    except Exception as e:
        logger.error(f"Favicon backfill task failed: {e}")


async def _set_cst_session(conn: asyncpg.Connection) -> None:
    """Pin every new connection to America/Chicago.

    Render runs containers in UTC and Aiven Postgres defaults the session to UTC
    too. The datalake stores timestamps already in CST, so without this every
    bare ``CURRENT_DATE`` / ``now()`` flips a day early between 18:00–23:59 CST.
    Pairs with ``app.clock.cst_today`` on the Python side.
    """
    await conn.execute("SET TIME ZONE 'America/Chicago'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()

    # This backend is publicly reachable and trusts the identity JSON in the
    # Authorization header. Without the shared secret, anyone can assert
    # roles:["admin"] and read every report — so make an unset value loud rather
    # than a silent fail-open. See config.PROXY_SHARED_SECRET / deps.require_user.
    if settings.PROXY_SHARED_SECRET:
        logger.info("Proxy shared secret: ENFORCED")
    else:
        logger.warning(
            "PROXY_SHARED_SECRET is not set — the API is accepting self-asserted "
            "identities from ANY caller. Set it on Render (and Vercel) to enable "
            "authentication."
        )

    if settings.DATABASE_URL:
        try:
            app.state.pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=2,
                max_size=10,
                # Fail fast (just under the proxy's 45s abort) so a runaway/cold
                # query releases its connection instead of hogging the pool.
                command_timeout=40,
                init=_set_cst_session,
            )
            # Ensure apps tables exist
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS apps (
                  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  title       TEXT NOT NULL,
                  url         TEXT NOT NULL,
                  description TEXT,
                  icon_data   TEXT,
                  is_active   BOOLEAN DEFAULT TRUE,
                  created_at  TIMESTAMPTZ DEFAULT NOW(),
                  updated_at  TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS app_role_access (
                  role_id  UUID REFERENCES roles(id) ON DELETE CASCADE,
                  app_id   UUID REFERENCES apps(id) ON DELETE CASCADE,
                  PRIMARY KEY (role_id, app_id)
                )
                """
            )
            # Add icon_data column if missing (existing DBs)
            await app.state.pool.execute(
                "ALTER TABLE apps ADD COLUMN IF NOT EXISTS icon_data TEXT"
            )
            # Add note column to reports if missing
            await app.state.pool.execute(
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS note TEXT"
            )
            # Add use_classic column for reports with Dashboard Bundle objects
            # (e.g. qlik-date-picker) that need classic/app embed mode
            await app.state.pool.execute(
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS use_classic BOOLEAN DEFAULT FALSE"
            )
            # Code-made reports (not embedded from Qlik) — report_type='custom'
            # + custom_path points to a Next.js route (e.g. /reports/esavings-carriers)
            await app.state.pool.execute(
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS report_type TEXT DEFAULT 'qlik'"
            )
            await app.state.pool.execute(
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS custom_path TEXT"
            )
            await app.state.pool.execute(
                "ALTER TABLE reports ALTER COLUMN qlik_app_id DROP NOT NULL"
            )
            # Ensure access_log table exists (for trending & usage tracking)
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS access_log (
                  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id     TEXT NOT NULL,
                  report_id   UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                  accessed_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_access_log_report_date ON access_log(report_id, accessed_at DESC)"
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_access_log_user ON access_log(user_id, accessed_at DESC)"
            )

            # KAM Performance - DFW (2026-05-19): per-user scratchpad tables.
            # Bruno's PDF: Tabs 1/4/5 are editable, Tab 3 has a free-text note.
            # Tabs 2 & 3 read data through ops-customer-score / xray-dfw-mng.
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_scorecards (
                  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id             TEXT NOT NULL,
                  customer            TEXT NOT NULL,
                  scorecard_date      DATE NOT NULL,
                  scorecard_frequency TEXT NOT NULL,
                  percentage          NUMERIC(6,2),
                  image_data          TEXT,
                  image_name          TEXT,
                  image_mime          TEXT,
                  uploaded_by_email   TEXT,
                  uploaded_by_name    TEXT,
                  created_at          TIMESTAMPTZ DEFAULT NOW(),
                  updated_at          TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_kam_scorecards_user ON kam_scorecards(user_id, scorecard_date DESC)"
            )
            # Backfill for databases created before the Bruno 2026-08-10 round
            # (numeric "Percentage" column + image upload).
            #
            # Guarded TWICE, deliberately:
            #  * outer — this whole lifespan block shares ONE `try` whose
            #    handler sets `pool = None`; an unguarded failure here would
            #    skip seeding and take the entire portal DB-less on a warning.
            #  * per statement — a shared try would let one failure (lock wait,
            #    statement timeout) skip the remaining ALTERs, leaving the table
            #    half-migrated. Every KAM-scorecard endpoint then 500s with
            #    `column "image_data" does not exist`, breaking a tab that
            #    worked fine before the deploy.
            for _stmt in (
                "ALTER TABLE kam_scorecards ADD COLUMN IF NOT EXISTS percentage NUMERIC(6,2)",
                "ALTER TABLE kam_scorecards ADD COLUMN IF NOT EXISTS image_data TEXT",
                "ALTER TABLE kam_scorecards ADD COLUMN IF NOT EXISTS image_name TEXT",
                "ALTER TABLE kam_scorecards ADD COLUMN IF NOT EXISTS image_mime TEXT",
                "ALTER TABLE kam_scorecards ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
            ):
                try:
                    await app.state.pool.execute(_stmt)
                except Exception as e:
                    logger.warning(f"kam_scorecards backfill failed [{_stmt}]: {e}")
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_customer_dev (
                  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id           TEXT NOT NULL,
                  contact_name      TEXT NOT NULL,
                  last_day_spoke    DATE,
                  opportunity_areas TEXT DEFAULT '',
                  action_plan       TEXT DEFAULT '',
                  created_at        TIMESTAMPTZ DEFAULT NOW(),
                  updated_at        TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_kam_customer_dev_user ON kam_customer_dev(user_id, last_day_spoke DESC NULLS LAST)"
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_team_dev (
                  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id         TEXT NOT NULL,
                  team_member     TEXT NOT NULL,
                  last_one_on_one TEXT DEFAULT '',
                  specific_area   TEXT DEFAULT '',
                  action_plan     TEXT DEFAULT '',
                  created_at      TIMESTAMPTZ DEFAULT NOW(),
                  updated_at      TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_kam_team_dev_user ON kam_team_dev(user_id, updated_at DESC)"
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_top_lanes_notes (
                  user_id    TEXT PRIMARY KEY,
                  notes      TEXT NOT NULL DEFAULT '',
                  updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # Booker Performance Scorecard (Bruno PDF 2026-08-10) — the
            # "Action Plan" box. One row per user, same shape as
            # kam_top_lanes_notes.
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS booker_scorecard_notes (
                  user_id    TEXT PRIMARY KEY,
                  notes      TEXT NOT NULL DEFAULT '',
                  updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # Keep-warm heartbeat ledger — one row per pinger, written by
            # /api/health. Feeds daily_keepwarm_check (services/keepwarm_monitor.py),
            # which is the ONLY visibility we have that the n8n primary is alive:
            # workflow aF3wH6ZpvDFEPXA5 has saveDataSuccessExecution="none" and no
            # errorWorkflow, so a silent stop surfaces nowhere in n8n itself.
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS keepwarm_pings (
                  source          TEXT PRIMARY KEY,
                  last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  ping_count      BIGINT      NOT NULL DEFAULT 1,
                  max_gap_seconds INTEGER     NOT NULL DEFAULT 0,
                  window_start    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # KAM round 2 (2026-05-26): per-lane editable annotations for the
            # new Worst-10-Lanes and Carrier-Sales tabs. Keyed by (user_id,
            # lane_key) so a KAM's expiration dates / action plans / comments
            # stick to the lane even as the worst-lane list reshuffles.
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_worst_lane_notes (
                  user_id         TEXT NOT NULL,
                  lane_key        TEXT NOT NULL,
                  expiration_date DATE,
                  action_plan     TEXT NOT NULL DEFAULT '',
                  updated_at      TIMESTAMPTZ DEFAULT NOW(),
                  PRIMARY KEY (user_id, lane_key)
                )
                """
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_carrier_comments (
                  user_id    TEXT NOT NULL,
                  lane_key   TEXT NOT NULL,
                  comments   TEXT NOT NULL DEFAULT '',
                  updated_at TIMESTAMPTZ DEFAULT NOW(),
                  PRIMARY KEY (user_id, lane_key)
                )
                """
            )
            # KAM Carrier Sales (Bruno PDF 2026-07-20): the Carrier Sales tab is
            # now a fully-manual per-user table — no datalake auto-populate. Every
            # column (lane, carrier, cost, moves, comments) is user-entered; rows
            # are private (user_id scoped) like customer-dev / team-dev.
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS kam_carrier_sales (
                  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id    TEXT NOT NULL,
                  lane       TEXT NOT NULL DEFAULT '',
                  carrier    TEXT NOT NULL DEFAULT '',
                  cost       NUMERIC,
                  moves      INTEGER,
                  comments   TEXT NOT NULL DEFAULT '',
                  created_at TIMESTAMPTZ DEFAULT NOW(),
                  updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_kam_carrier_sales_user ON kam_carrier_sales(user_id, updated_at DESC)"
            )

            # Bonus Calculator (2026-05-24): HR-editable roster / afterhours /
            # FX settings / month-lock. Team metrics come from the live datalake;
            # these tables hold the HR data McLeod can't provide. Seeded once
            # from the package template (see services/bonus_defaults.py).
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS bonus_roster (
                  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  team_id       TEXT NOT NULL,
                  employee_name TEXT NOT NULL,
                  role          TEXT NOT NULL,
                  salary_mxn    NUMERIC NOT NULL DEFAULT 0,
                  sort_order    INTEGER NOT NULL DEFAULT 0,
                  created_at    TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_bonus_roster_team ON bonus_roster(team_id, sort_order)"
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS bonus_afterhours (
                  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  shift_group    TEXT NOT NULL,
                  employee_name  TEXT NOT NULL,
                  salary_mxn     NUMERIC NOT NULL DEFAULT 0,
                  receives_bonus BOOLEAN NOT NULL DEFAULT TRUE,
                  sort_order     INTEGER NOT NULL DEFAULT 0,
                  created_at     TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS bonus_settings (
                  period_key TEXT PRIMARY KEY,
                  team_fx    NUMERIC NOT NULL,
                  night_fx   NUMERIC NOT NULL,
                  updated_by TEXT,
                  updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS bonus_period_lock (
                  period_key  TEXT PRIMARY KEY,
                  status      TEXT NOT NULL DEFAULT 'open',
                  approved_by TEXT,
                  approved_at TIMESTAMPTZ
                )
                """
            )
            # Immutable monthly snapshot (Bruno 2026-05-28). Finalized at the
            # cutoff (6th of the next month 23:59 CST) by daily_bonus_history_finalize.
            await app.state.pool.execute(
                """
                CREATE TABLE IF NOT EXISTS bonus_history (
                  period_key      TEXT NOT NULL,
                  team_id         TEXT NOT NULL,
                  team_name       TEXT NOT NULL,
                  profit_usd      NUMERIC NOT NULL,
                  total_bonus_usd NUMERIC NOT NULL,
                  pct_bonus       NUMERIC,
                  finalized_at    TIMESTAMPTZ DEFAULT NOW(),
                  PRIMARY KEY (period_key, team_id)
                )
                """
            )
            try:
                from app.services.bonus_defaults import seed_bonus_data

                await seed_bonus_data(app.state.pool)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Bonus Calculator seed skipped: {e}")

            # Auto-seed if no role-report mappings exist
            count = await app.state.pool.fetchval(
                "SELECT COUNT(*) FROM role_report_access"
            )
            if count == 0:
                logger.info("No role-report mappings found, running seed...")
                from app.services.seed import seed_all

                await seed_all()

            # Always idempotently upsert code-made (custom) reports so new
            # entries added to CUSTOM_REPORTS ship on the next deploy — the
            # full seed_all only runs once (when role_report_access is empty).
            try:
                from app.services.seed import seed_custom_reports

                n = await seed_custom_reports(app.state.pool)
                logger.info(f"Custom reports upserted: {n}")
            except Exception as e:
                logger.warning(f"Custom-reports upsert skipped: {e}")

            # Schedule favicon backfill as background task (not blocking startup)
            asyncio.create_task(_backfill_favicons(app.state.pool))
        except Exception as e:
            logger.warning(f"Database startup error: {e}. Running without DB.")
            app.state.pool = None
    else:
        app.state.pool = None

    # Second pool for the aivn_datalake_gold DB (carrier savings source)
    if settings.SAVINGS_DATABASE_URL:
        try:
            app.state.savings_pool = await asyncpg.create_pool(
                settings.SAVINGS_DATABASE_URL,
                # This pool now backs ~23 code-made reports (the whole exec/ops
                # suite). Heavy pages (ops-portal-overview) fan out 10-15 panels
                # concurrently, so 4 connections starved the queue. 2/8 + a
                # 42s command_timeout (just under the proxy's 45s abort) lets
                # slow/cold queries fail fast and free their connection.
                min_size=2,
                max_size=8,
                command_timeout=42,
                init=_set_cst_session,
            )
            logger.info(
                "Datalake (gold) pool connected — powers the exec/ops report suite (~23 reports)"
            )
        except Exception as e:
            logger.warning(
                f"Datalake (gold) DB connect failed: {e}. "
                "eSavings & Budget Follow Up will 503."
            )
            app.state.savings_pool = None
    else:
        app.state.savings_pool = None

    # Third pool for automations_db (n8n-produced tables, e.g.
    # contract_performance_analysis -> Track Award Loads).
    if settings.AUTOMATIONS_DATABASE_URL:
        try:
            app.state.automations_pool = await asyncpg.create_pool(
                settings.AUTOMATIONS_DATABASE_URL,
                min_size=1,
                max_size=4,
                command_timeout=40,
                init=_set_cst_session,
            )
            logger.info(
                "Automations pool connected — powers Track Award Loads"
            )
        except Exception as e:
            logger.warning(
                f"Automations DB connect failed: {e}. Track Award Loads will 503."
            )
            app.state.automations_pool = None
    else:
        app.state.automations_pool = None

    # Fourth pool for fresh_services_unlk (FreshService Tickets/Agents mirror,
    # populated by an external Spark ETL). Powers IT Tickets Mgmt report.
    if settings.FRESHSERVICE_DATABASE_URL:
        try:
            app.state.freshservice_pool = await asyncpg.create_pool(
                settings.FRESHSERVICE_DATABASE_URL,
                min_size=1,
                max_size=4,
                command_timeout=40,
                init=_set_cst_session,
            )
            logger.info(
                "FreshService pool connected — powers IT Tickets Mgmt"
            )
        except Exception as e:
            logger.warning(
                f"FreshService DB connect failed: {e}. IT Tickets Mgmt will 503."
            )
            app.state.freshservice_pool = None
    else:
        app.state.freshservice_pool = None

    # Pool for modern_pricing_portal (the quoting portal's own DB). Read-only,
    # SELECT on spot_report_condensed only. Powers the HD Spot report's funnel
    # half; the money half comes from the gold pool and is merged in Python
    # (the two are separate databases — no dblink/fdw, see §56).
    if settings.PRICING_DATABASE_URL:
        try:
            app.state.pricing_pool = await asyncpg.create_pool(
                settings.PRICING_DATABASE_URL,
                min_size=1,
                max_size=4,
                command_timeout=40,
                init=_set_cst_session,
            )
            logger.info("Pricing portal pool connected — powers HD Spot")
        except Exception as e:
            logger.warning(
                f"Pricing portal DB connect failed: {e}. HD Spot will 503."
            )
            app.state.pricing_pool = None
    else:
        app.state.pricing_pool = None

    # Fifth pool for unilink_portal_ap (the AP_module app's own DB — carriers +
    # fmcsa_sms_data). Read-only. Powers the Carrier SMS Score report.
    if settings.AP_DATABASE_URL:
        try:
            app.state.ap_pool = await asyncpg.create_pool(
                settings.AP_DATABASE_URL,
                min_size=1,
                max_size=4,
                command_timeout=40,
                init=_set_cst_session,
            )
            logger.info(
                "Carrier (AP) pool connected — powers Carrier SMS Score"
            )
        except Exception as e:
            logger.warning(
                f"Carrier (AP) DB connect failed: {e}. Carrier SMS Score will 503."
            )
            app.state.ap_pool = None
    else:
        app.state.ap_pool = None

    # Optional read-only pool for UNLK-Financial's exchange_rates (Banxico FIX =
    # DOF). Used only to PREFILL a suggested FX on Bonus Calculator; HR's pinned
    # rate is authoritative, so the report works fine when this is unset.
    if settings.FINANCIAL_DATABASE_URL:
        try:
            app.state.financial_pool = await asyncpg.create_pool(
                settings.FINANCIAL_DATABASE_URL,
                min_size=1,
                max_size=2,
                command_timeout=40,
                init=_set_cst_session,
            )
            logger.info("Financial pool connected — Bonus Calculator DOF FX suggestion")
        except Exception as e:
            logger.warning(
                f"Financial DB connect failed: {e}. Bonus Calculator FX suggestion disabled."
            )
            app.state.financial_pool = None
    else:
        app.state.financial_pool = None

    # Schedule daily user sync at 2:00 AM CST (America/Chicago)
    if settings.TIMEOFF_DATABASE_URL:
        scheduler.add_job(
            _scheduled_user_sync,
            CronTrigger(hour=2, minute=0, timezone="America/Chicago"),
            id="daily_user_sync",
            name="Sync users from time-off DB",
            replace_existing=True,
        )

    # Schedule daily Losses Lanes weekly-movers email at 7:00 AM CST.
    # Runs regardless of TIMEOFF_DATABASE_URL since it only needs the
    # savings_pool (aivn_datalake_gold) + RESEND_API_KEY.
    if settings.SAVINGS_DATABASE_URL and settings.RESEND_API_KEY:
        scheduler.add_job(
            _scheduled_losses_alert,
            CronTrigger(hour=7, minute=0, timezone="America/Chicago"),
            id="daily_losses_alert",
            name="Send Losses Lanes weekly-movers email",
            replace_existing=True,
        )
        logger.info(
            "Scheduled daily Losses Lanes alert at 7:00 AM CST "
            "(msalazarm + dfrodriguez)"
        )
    else:
        missing = []
        if not settings.SAVINGS_DATABASE_URL:
            missing.append("SAVINGS_DATABASE_URL")
        if not settings.RESEND_API_KEY:
            missing.append("RESEND_API_KEY")
        logger.warning(
            "Losses alert NOT scheduled — missing env vars: %s", ", ".join(missing)
        )

    # Schedule daily Bonus Calculator history finalize at 1:00 AM CST. Needs the
    # primary pool (bonus_history) + the gold pool (savings_pool) to recompute a
    # closed month; runs daily so it self-backfills past months on first deploy.
    if settings.SAVINGS_DATABASE_URL:
        scheduler.add_job(
            _scheduled_bonus_history_finalize,
            CronTrigger(hour=1, minute=0, timezone="America/Chicago"),
            id="daily_bonus_history_finalize",
            name="Finalize Bonus Calculator monthly history snapshots",
            replace_existing=True,
        )
        logger.info("Scheduled Bonus Calculator history finalize at 1:00 AM CST")

    # Schedule nightly lane_market_rates pre-warm at 5:00 AM CST. Skips when
    # neither SONAR nor 123LB credentials are present (the prewarm just no-ops).
    if settings.SAVINGS_DATABASE_URL:
        scheduler.add_job(
            _scheduled_lane_rates_prewarm,
            CronTrigger(hour=5, minute=0, timezone="America/Chicago"),
            id="daily_lane_rates_prewarm",
            name="Pre-warm SONAR + 123LB lane market rates",
            replace_existing=True,
        )
        logger.info("Scheduled lane-rates prewarm at 5:00 AM CST")

    # Keep the datalake (gold) Postgres buffers hot every 5 min so heavy report
    # queries never pay the 20-28s cold-scan penalty on a user's first hit.
    # /api/health pings keep the dyno warm but issue zero DB queries; this fills
    # that gap. Best-effort, in-process (ASGITransport), log-and-swallow.
    if settings.SAVINGS_DATABASE_URL:
        scheduler.add_job(
            _scheduled_datalake_warmup,
            IntervalTrigger(minutes=5),
            id="datalake_warmup",
            name="Warm datalake gold shared buffers (ops-portal-overview queries)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduled datalake warmup every 5 min")

    # Schedule daily scorecard-mirror freshness watchdog — 6:15 AM CST. The
    # portal reads an n8n TRUNCATE+load mirror (mcleod_gld_scorecard_portal) that
    # can't bloat, so we watch freshness instead: alert if the n8n refresh has
    # stalled or the mirror is missing/empty. SELECT-only + RESEND_API_KEY.
    if settings.SAVINGS_DATABASE_URL and settings.RESEND_API_KEY:
        scheduler.add_job(
            _scheduled_scorecard_mirror_check,
            CronTrigger(hour=6, minute=15, timezone="America/Chicago"),
            id="daily_scorecard_mirror_check",
            name="Watch mcleod_gld_scorecard_portal mirror freshness",
            replace_existing=True,
        )
        logger.info("Scheduled scorecard mirror freshness check daily 6:15 AM CST")

    # Schedule daily keep-warm watchdog — 6:10 AM CST, just before the scorecard
    # check so the two ops alerts land together. Alerts only when a pinger has
    # stalled; quiet when healthy. Needs analytics_hub (keepwarm_pings) + Resend.
    if settings.RESEND_API_KEY:
        scheduler.add_job(
            _scheduled_keepwarm_check,
            CronTrigger(hour=6, minute=10, timezone="America/Chicago"),
            id="daily_keepwarm_check",
            name="Watch backend keep-warm pingers (n8n primary + systemd backstop)",
            replace_existing=True,
        )
        logger.info("Scheduled keep-warm watchdog daily 6:10 AM CST")

    # Schedule daily RFP Performance digest at 5:30 PM CST (Mon-Fri only).
    # Needs the automations_db pool (rfp_results_history) and MS Graph creds.
    if (
        settings.AUTOMATIONS_DATABASE_URL
        and settings.MS_TENANT_ID
        and settings.MS_CLIENT_ID
        and settings.MS_CLIENT_SECRET
    ):
        scheduler.add_job(
            _scheduled_rfp_digest,
            CronTrigger(
                day_of_week="mon-fri",
                hour=17,
                minute=30,
                timezone="America/Chicago",
            ),
            id="daily_rfp_digest",
            name="Send RFP Performance daily digest",
            replace_existing=True,
        )
        logger.info(
            "Scheduled daily RFP Performance digest at 17:30 CST (Mon-Fri) "
            "from %s",
            settings.MS_SEND_FROM,
        )
    else:
        missing = []
        if not settings.AUTOMATIONS_DATABASE_URL:
            missing.append("AUTOMATIONS_DATABASE_URL")
        if not settings.MS_TENANT_ID:
            missing.append("MS_TENANT_ID")
        if not settings.MS_CLIENT_ID:
            missing.append("MS_CLIENT_ID")
        if not settings.MS_CLIENT_SECRET:
            missing.append("MS_CLIENT_SECRET")
        logger.warning(
            "RFP digest NOT scheduled — missing env vars: %s", ", ".join(missing)
        )

    # Schedule Ops Portal "Team" digest twice daily 06:00 + 18:00 CST (Bruno R9).
    # Reads the datalake in-process via ASGITransport; needs MS Graph creds (the
    # SAVINGS pool is loaded for the endpoint it calls) and the datalake pool.
    if (
        settings.SAVINGS_DATABASE_URL
        and settings.MS_TENANT_ID
        and settings.MS_CLIENT_ID
        and settings.MS_CLIENT_SECRET
    ):
        scheduler.add_job(
            _scheduled_ops_team_digest,
            CronTrigger(hour="6,18", minute=0, timezone="America/Chicago"),
            id="ops_team_digest",
            name="Send Ops Portal Team Monthly Performance digest (06:00 & 18:00 CST)",
            replace_existing=True,
        )
        logger.info(
            "Scheduled Ops Portal Team digest at 06:00 & 18:00 CST from %s",
            settings.MS_SEND_FROM,
        )
    else:
        logger.warning("Ops Portal Team digest NOT scheduled — missing env vars")

    if scheduler.get_jobs():
        scheduler.start()

    yield

    scheduler.shutdown(wait=False)
    if app.state.pool:
        await app.state.pool.close()
    if getattr(app.state, "savings_pool", None):
        await app.state.savings_pool.close()
    if getattr(app.state, "automations_pool", None):
        await app.state.automations_pool.close()
    if getattr(app.state, "freshservice_pool", None):
        await app.state.freshservice_pool.close()
    if getattr(app.state, "pricing_pool", None):
        await app.state.pricing_pool.close()


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Analytics Hub API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _timing_log(request: Request, call_next):
    """Log wall-clock duration for every request so we can pinpoint slow endpoints.

    Only emits for custom-report routes to keep logs focused. Render log stream
    → search `perf route=/api/custom/xray-corp` to see durations per endpoint.
    """
    path = request.url.path
    if not path.startswith("/api/custom/"):
        return await call_next(request)
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "perf route=%s status=%s duration_ms=%s qs=%s",
        path, response.status_code, duration_ms, request.url.query or "-",
    )
    return response

app.include_router(search.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(reports_index.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(carriers_savings.router, prefix="/api")
app.include_router(budget_followup.router, prefix="/api")
app.include_router(xray_corp.router, prefix="/api")
app.include_router(xray_dfw.router, prefix="/api")
for _team_router in xray_dfw_team.team_routers:
    app.include_router(_team_router, prefix="/api")
app.include_router(ceo_executive.router, prefix="/api")
app.include_router(ceo_cockpit.router, prefix="/api")
app.include_router(hr_access_doors.router, prefix="/api")
# Scope-locked Access Log Doors clones — all five share one factory
# (`scoped_access_doors.py`); DFW + Admin migrated onto it 2026-08-12.
app.include_router(scoped_access_doors.dfw_router, prefix="/api")
app.include_router(scoped_access_doors.admin_router, prefix="/api")
app.include_router(scoped_access_doors.ops_router, prefix="/api")
app.include_router(scoped_access_doors.pricing_router, prefix="/api")
app.include_router(scoped_access_doors.carrier_procurement_router, prefix="/api")
app.include_router(podium_dfw.router, prefix="/api")
app.include_router(booker_scorecard.router, prefix="/api")
app.include_router(hd_spot.router, prefix="/api")
app.include_router(podium_top.router, prefix="/api")
for _podium_team_router in podium_top.team_routers:
    app.include_router(_podium_team_router, prefix="/api")
app.include_router(losses_lanes.router, prefix="/api")
app.include_router(dfw_losses.router, prefix="/api")
app.include_router(attrition_wow.router, prefix="/api")
app.include_router(ops_margins.router, prefix="/api")
app.include_router(ops_direct_compare.router, prefix="/api")
for _odc_team_router in ops_direct_compare_team.team_routers:
    app.include_router(_odc_team_router, prefix="/api")
app.include_router(ops_customer_score.router, prefix="/api")
for _ocs_team_router in ops_customer_score_team.team_routers:
    app.include_router(_ocs_team_router, prefix="/api")
app.include_router(ops_portal_overview.router, prefix="/api")
for _opo_team_router in ops_portal_overview_team.team_routers:
    app.include_router(_opo_team_router, prefix="/api")
# "Performance for Team N" e-mail digest — same /custom/ops-portal-overview
# prefix, own module so the 3.9k-line UI router stays untouched. Pulled by n8n.
app.include_router(ops_team_perf_digest.router, prefix="/api")
app.include_router(sales_attrition_to_ops.router, prefix="/api")
app.include_router(voip_calls.router, prefix="/api")
app.include_router(track_award_loads.router, prefix="/api")
app.include_router(rfp_performance.router, prefix="/api")
app.include_router(carrier_risk.router, prefix="/api")
app.include_router(carrier_sms.router, prefix="/api")
app.include_router(it_tickets.router, prefix="/api")
app.include_router(admin_cashflow.router, prefix="/api")
app.include_router(kam_performance_dfw.router, prefix="/api")
app.include_router(bonus_calculator.router, prefix="/api")


@app.get("/api/health")
async def health(request: Request):
    # Record keep-warm heartbeats so daily_keepwarm_check can tell whether the
    # n8n primary is still firing (it has no failure visibility of its own).
    # STRICTLY best-effort: /api/health must keep returning 200 even if the DB
    # is down, or a DB blip would make both pingers log a false failure.
    try:
        source = classify_keepwarm_source(
            request.headers.get("user-agent"),
            request.headers.get("x-forwarded-for"),
        )
        pool = getattr(app.state, "pool", None)
        if source and pool is not None:
            await pool.execute(
                """
                INSERT INTO keepwarm_pings (source, last_seen, ping_count, max_gap_seconds, window_start)
                VALUES ($1, NOW(), 1, 0, NOW())
                ON CONFLICT (source) DO UPDATE SET
                  last_seen       = NOW(),
                  ping_count      = keepwarm_pings.ping_count + 1,
                  max_gap_seconds = GREATEST(
                      keepwarm_pings.max_gap_seconds,
                      EXTRACT(EPOCH FROM (NOW() - keepwarm_pings.last_seen))::int
                  )
                """,
                source,
            )
    except Exception:  # noqa: BLE001 - health must never fail on bookkeeping
        logger.debug("keepwarm ping not recorded", exc_info=True)

    return {"status": "ok"}
