from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.routers import admin, preferences, qlik, reports, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(
        settings.DATABASE_URL, min_size=2, max_size=10
    )
    yield
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
