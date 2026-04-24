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
    budget_followup,
    carriers_savings,
    ceo_executive,
    hr_access_doors,
    podium_dfw,
    preferences,
    qlik,
    reports,
    search,
    xray_corp,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()

    if settings.DATABASE_URL:
        try:
            app.state.pool = await asyncpg.create_pool(
                settings.DATABASE_URL, min_size=2, max_size=10
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

            # Auto-seed if no role-report mappings exist
            count = await app.state.pool.fetchval(
                "SELECT COUNT(*) FROM role_report_access"
            )
            if count == 0:
                logger.info("No role-report mappings found, running seed...")
                from app.services.seed import seed_all

                await seed_all()

            # One-time migration (idempotent): flip the legacy "HR - Access Log
            # Doors" Qlik row (app 4573ff42-…, sheet ZYDdxs on unilink.us) to a
            # code-made row pointing at /reports/hr-access-doors. Runs on every
            # boot but no-ops once the row has been converted. Also removes the
            # obsolete "(Mob) HR - Access Log Doors" mobile duplicate.
            try:
                await app.state.pool.execute(
                    """
                    UPDATE reports
                       SET qlik_app_id   = NULL,
                           qlik_sheet_id = NULL,
                           report_type   = 'custom',
                           custom_path   = '/reports/hr-access-doors',
                           is_active     = TRUE
                     WHERE qlik_app_id = '4573ff42-c0b5-48ef-9945-20861b7a6f63'
                       AND (custom_path IS NULL OR custom_path <> '/reports/hr-access-doors')
                    """
                )
                await app.state.pool.execute(
                    """
                    DELETE FROM reports
                     WHERE title = '(Mob) HR - Access Log Doors'
                    """
                )
            except Exception as e:
                logger.warning(f"HR Access Log migration skipped: {e}")

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
                settings.SAVINGS_DATABASE_URL, min_size=1, max_size=4
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

    # Schedule daily user sync at 2:00 AM CST (America/Chicago)
    if settings.TIMEOFF_DATABASE_URL:
        scheduler.add_job(
            _scheduled_user_sync,
            CronTrigger(hour=2, minute=0, timezone="America/Chicago"),
            id="daily_user_sync",
            name="Sync users from time-off DB",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduled daily user sync at 2:00 AM CST")

    yield

    scheduler.shutdown(wait=False)
    if app.state.pool:
        await app.state.pool.close()
    if getattr(app.state, "savings_pool", None):
        await app.state.savings_pool.close()


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
app.include_router(qlik.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(carriers_savings.router, prefix="/api")
app.include_router(budget_followup.router, prefix="/api")
app.include_router(xray_corp.router, prefix="/api")
app.include_router(ceo_executive.router, prefix="/api")
app.include_router(hr_access_doors.router, prefix="/api")
app.include_router(podium_dfw.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
