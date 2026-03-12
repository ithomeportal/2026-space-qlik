from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.routers.deps import get_pool, require_user

router = APIRouter(tags=["preferences"])


class PreferencesUpdate(BaseModel):
    pinned_reports: list[UUID] | None = None
    recent_reports: list[UUID] | None = None
    theme: str | None = None


@router.get("/user/preferences")
async def get_preferences(
    request: Request,
    user: dict = Depends(require_user),
):
    pool = get_pool(request)
    user_id = user["sub"]

    row = await pool.fetchrow(
        "SELECT * FROM user_preferences WHERE user_id = $1",
        user_id,
    )

    if not row:
        return {
            "success": True,
            "data": {
                "pinned_reports": [],
                "recent_reports": [],
                "theme": "light",
            },
        }

    return {"success": True, "data": dict(row)}


@router.patch("/user/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    request: Request,
    user: dict = Depends(require_user),
):
    pool = get_pool(request)
    user_id = user["sub"]

    # Upsert preferences
    await pool.execute(
        """
        INSERT INTO user_preferences (user_id, pinned_reports, recent_reports, theme)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE SET
          pinned_reports = COALESCE($2, user_preferences.pinned_reports),
          recent_reports = COALESCE($3, user_preferences.recent_reports),
          theme = COALESCE($4, user_preferences.theme)
        """,
        user_id,
        [str(r) for r in body.pinned_reports] if body.pinned_reports else None,
        [str(r) for r in body.recent_reports] if body.recent_reports else None,
        body.theme,
    )

    return {"success": True, "data": {"updated": True}}
