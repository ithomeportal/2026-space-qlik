import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.routers import admin, preferences, qlik, reports, search

logger = logging.getLogger(__name__)


async def _scheduled_user_sync():
    """Background job: sync users from time-off DB."""
    try:
        from app.services.sync_users import sync_users

        result = await sync_users()
        logger.info(f"Scheduled user sync complete: {result}")
    except Exception as e:
        logger.error(f"Scheduled user sync failed: {e}")


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

            # Backfill favicons for apps missing or with Google globe placeholder
            apps_without_icons = await app.state.pool.fetch(
                """SELECT id, url FROM apps
                   WHERE is_active = TRUE
                     AND (icon_data IS NULL
                          OR icon_data LIKE 'data:image/png;base64,%')"""
            )
            if apps_without_icons:
                logger.info(
                    f"Backfilling favicons for {len(apps_without_icons)} apps..."
                )
                from app.routers.admin import _fetch_favicon

                for row in apps_without_icons:
                    icon_data = await _fetch_favicon(row["url"])
                    if icon_data:
                        await app.state.pool.execute(
                            "UPDATE apps SET icon_data = $1 WHERE id = $2",
                            icon_data,
                            row["id"],
                        )
                        logger.info(f"Favicon backfilled for app {row['id']}")
                    else:
                        logger.warning(
                            f"Could not fetch favicon for {row['url']}"
                        )
        except Exception as e:
            logger.warning(f"Database startup error: {e}. Running without DB.")
            app.state.pool = None
    else:
        app.state.pool = None

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

app.include_router(search.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(qlik.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
