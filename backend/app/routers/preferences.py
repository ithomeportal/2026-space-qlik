from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.routers.deps import get_pool, require_user, user_uuid

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
    user_id = user_uuid(user)

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
    user_id = user_uuid(user)

    # Upsert preferences
    await pool.execute(
        """
        INSERT INTO user_preferences (user_id, pinned_reports, recent_reports, theme)
        VALUES (
          $1,
          COALESCE($2, '{}'::uuid[]),
          COALESCE($3, '{}'::uuid[]),
          -- An explicit NULL OVERRIDES a column DEFAULT; it does not fall back
          -- to it. `theme` is NOT NULL DEFAULT 'light' in the live table (a
          -- Prisma-era definition the startup `CREATE TABLE IF NOT EXISTS`
          -- never revisited), so starring a report -- which PATCHes only
          -- `pinned_reports` and leaves `theme` None -- bound NULL here and
          -- raised NotNullViolationError. The COALESCEs on the DO UPDATE arm
          -- below hid it: only a user with NO row yet took the INSERT arm, and
          -- on 2026-08-18 that was ALL 147 of them (the table had 0 rows), so
          -- every first star click 500'd. Defaults belong on both arms.
          COALESCE($4, 'light')
        )
        ON CONFLICT (user_id) DO UPDATE SET
          pinned_reports = COALESCE($2, user_preferences.pinned_reports),
          recent_reports = COALESCE($3, user_preferences.recent_reports),
          theme = COALESCE($4, user_preferences.theme)
        """,
        user_id,
        # `is not None`, NOT truthiness: an empty list is falsy, so `if
        # body.pinned_reports` sent NULL for "clear the list" and the COALESCE
        # above then kept the OLD value. Un-favouriting your last report
        # silently did nothing. Same trap for recent_reports.
        [str(r) for r in body.pinned_reports] if body.pinned_reports is not None else None,
        [str(r) for r in body.recent_reports] if body.recent_reports is not None else None,
        body.theme,
    )

    return {"success": True, "data": {"updated": True}}
