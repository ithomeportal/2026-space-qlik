import asyncio
import logging
import time
from contextlib import asynccontextmanager

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.routers import (
    admin,
    admin_cashflow,
    attrition_wow,
    bonus_calculator,
    budget_followup,
    carrier_risk,
    admin_access_doors,
    carriers_savings,
    ceo_executive,
    dfw_access_doors,
    hr_access_doors,
    it_tickets,
    kam_performance_dfw,
    losses_lanes,
    ops_customer_score,
    ops_direct_compare,
    ops_margins,
    ops_portal_overview,
    podium_dfw,
    podium_top,
    preferences,
    reports,
    rfp_performance,
    sales_attrition_to_ops,
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

    if settings.DATABASE_URL:
        try:
            app.state.pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=2,
                max_size=10,
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
                  uploaded_by_email   TEXT,
                  uploaded_by_name    TEXT,
                  created_at          TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await app.state.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_kam_scorecards_user ON kam_scorecards(user_id, scorecard_date DESC)"
            )
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
                min_size=1,
                max_size=4,
                init=_set_cst_session,
            )
            logger.info(
                "Datalake (gold) pool connected — powers eSavings, Budget Follow Up & XRay CORP Mng"
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

    # Optional read-only pool for UNLK-Financial's exchange_rates (Banxico FIX =
    # DOF). Used only to PREFILL a suggested FX on Bonus Calculator; HR's pinned
    # rate is authoritative, so the report works fine when this is unset.
    if settings.FINANCIAL_DATABASE_URL:
        try:
            app.state.financial_pool = await asyncpg.create_pool(
                settings.FINANCIAL_DATABASE_URL,
                min_size=1,
                max_size=2,
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
app.include_router(preferences.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(carriers_savings.router, prefix="/api")
app.include_router(budget_followup.router, prefix="/api")
app.include_router(xray_corp.router, prefix="/api")
app.include_router(xray_dfw.router, prefix="/api")
for _team_router in xray_dfw_team.team_routers:
    app.include_router(_team_router, prefix="/api")
app.include_router(ceo_executive.router, prefix="/api")
app.include_router(hr_access_doors.router, prefix="/api")
app.include_router(dfw_access_doors.router, prefix="/api")
app.include_router(admin_access_doors.router, prefix="/api")
app.include_router(podium_dfw.router, prefix="/api")
app.include_router(podium_top.router, prefix="/api")
app.include_router(losses_lanes.router, prefix="/api")
app.include_router(attrition_wow.router, prefix="/api")
app.include_router(ops_margins.router, prefix="/api")
app.include_router(ops_direct_compare.router, prefix="/api")
app.include_router(ops_customer_score.router, prefix="/api")
app.include_router(ops_portal_overview.router, prefix="/api")
app.include_router(sales_attrition_to_ops.router, prefix="/api")
app.include_router(voip_calls.router, prefix="/api")
app.include_router(track_award_loads.router, prefix="/api")
app.include_router(rfp_performance.router, prefix="/api")
app.include_router(carrier_risk.router, prefix="/api")
app.include_router(it_tickets.router, prefix="/api")
app.include_router(admin_cashflow.router, prefix="/api")
app.include_router(kam_performance_dfw.router, prefix="/api")
app.include_router(bonus_calculator.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
