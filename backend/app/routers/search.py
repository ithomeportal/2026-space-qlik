from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_pool, require_user

router = APIRouter(tags=["search"])


@router.get("/reports/search")
async def search_reports(
    request: Request,
    q: str = Query(..., min_length=1),
    category: Optional[str] = Query(None),
    user: dict = Depends(require_user),
    limit: int = Query(20, ge=1, le=50),
):
    pool = get_pool(request)
    user_id = user["sub"]
    pattern = f"%{q}%"

    # Search reports by title, description, note, tags
    report_rows = await pool.fetch(
        """
        SELECT DISTINCT r.id, r.qlik_app_id, r.qlik_sheet_id, r.title,
               r.description, r.note, r.category, r.tags, r.owner_name,
               r.data_sources, r.last_reload,
               'report' AS result_type
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.is_active = TRUE
          AND (r.title ILIKE $2
               OR r.description ILIKE $2
               OR r.note ILIKE $2
               OR $3 = ANY(r.tags))
          AND ($4::text IS NULL OR r.category = $4)
        LIMIT $5
        """,
        user_id,
        pattern,
        q.lower(),
        category,
        limit,
    )

    # Search apps by title and description (visible to all authenticated users)
    app_rows = await pool.fetch(
        """
        SELECT id, title, description, url, icon_data,
               'app' AS result_type
        FROM apps
        WHERE is_active = TRUE
          AND (title ILIKE $1 OR description ILIKE $1)
        LIMIT $2
        """,
        pattern,
        limit,
    )

    # Combine results: reports first, then apps
    data = [dict(r) for r in report_rows] + [dict(r) for r in app_rows]

    return {
        "success": True,
        "data": data,
        "meta": {"total": len(data)},
    }
