"""GET /api/data-status/gold — feeds the report-chrome banner (§143 v5).

Any signed-in user: it reveals only when the McLeod load last wrote, no report
data. Never 500s — a report page must not break over its banner.
"""

from fastapi import APIRouter, Depends, Request

from app.routers.deps import require_user
from app.services.gold_status import gold_status

router = APIRouter(tags=["data-status"])


@router.get("/data-status/gold")
async def get_gold_status(request: Request, user: dict = Depends(require_user)) -> dict:
    pool = getattr(request.app.state, "savings_pool", None)
    return {"success": True, "data": await gold_status(pool)}
