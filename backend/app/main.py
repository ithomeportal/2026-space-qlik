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
            # Auto-seed if no role-report mappings exist
            count = await app.state.pool.fetchval(
                "SELECT COUNT(*) FROM role_report_access"
            )
            if count == 0:
                logger.info("No role-report mappings found, running seed...")
                from app.services.seed import seed_all

                await seed_all()
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

app.include_router(reports.router, prefix="/api")
app.include_router(qlik.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
