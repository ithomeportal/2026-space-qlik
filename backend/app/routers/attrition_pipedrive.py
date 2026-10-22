"""Attrition → Pipedrive — admin surface over the 04:00 CST job.

    GET  /api/custom/attrition-pipedrive/preview     what a run would do NOW (read-only)
    GET  /api/custom/attrition-pipedrive/log?days=   actions + runs
    POST /api/custom/attrition-pipedrive/run         run NOW — honours ATTRITION_PIPEDRIVE_LIVE

ADMIN only. The prefix is not a report key, so the Teams AI assistant cannot
reach these routes (they write to Pipedrive and send mail).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import settings
from app.routers.deps import require_admin
from app.services.attrition_pipedrive.candidates import StaleFeedError
from app.services.attrition_pipedrive.pipedrive import PipedriveError
from app.services.attrition_pipedrive.runner import (
    LOG_SQL,
    RUNS_SQL,
    RunFailed,
    run_daily,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attrition-pipedrive"], prefix="/custom/attrition-pipedrive")


def _require_configured(request: Request) -> None:
    if not (settings.PIPEDRIVE_DOMAIN and settings.PIPEDRIVE_API_TOKEN):
        raise HTTPException(status_code=503, detail="Pipedrive not configured")
    if getattr(request.app.state, "savings_pool", None) is None:
        raise HTTPException(status_code=503, detail="datalake not configured")


async def _run(request: Request, *, live: bool, record: bool) -> dict:
    _require_configured(request)
    try:
        result = await run_daily(request.app, live=live, record=record)
    except RunFailed as e:
        return {"success": False, "data": e.result.as_dict(), "error": str(e)}
    except StaleFeedError as e:
        raise HTTPException(status_code=503, detail=f"stale feed: {e}") from None
    except PipedriveError as e:
        logger.error("attrition→pipedrive: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from None
    return {"success": True, "data": result.as_dict()}


@router.get("/preview")
async def preview(request: Request, _admin: dict = Depends(require_admin)):
    return await _run(request, live=False, record=False)


@router.post("/run")
async def run_now(request: Request, _admin: dict = Depends(require_admin)):
    if not settings.ATTRITION_PIPEDRIVE_ENABLED:
        raise HTTPException(status_code=409, detail="ATTRITION_PIPEDRIVE_ENABLED is off")
    return await _run(request, live=settings.ATTRITION_PIPEDRIVE_LIVE, record=True)


def _row(r) -> dict:
    out = dict(r)
    for k, v in out.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    if isinstance(out.get("counts"), str):
        out["counts"] = json.loads(out["counts"])
    return out


@router.get("/log")
async def log(
    request: Request,
    days: int = Query(14, ge=1, le=365),
    _admin: dict = Depends(require_admin),
):
    pool = request.app.state.pool
    actions = [_row(r) for r in await pool.fetch(LOG_SQL, days)]
    runs = [_row(r) for r in await pool.fetch(RUNS_SQL, days)]
    return {"success": True, "data": {"actions": actions, "runs": runs},
            "meta": {"live": settings.ATTRITION_PIPEDRIVE_LIVE,
                     "enabled": settings.ATTRITION_PIPEDRIVE_ENABLED}}
