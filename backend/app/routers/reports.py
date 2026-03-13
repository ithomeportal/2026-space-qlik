from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_pool, require_user

router = APIRouter(tags=["reports"])


@router.get("/reports")
async def list_reports(
    request: Request,
    user: dict = Depends(require_user),
    category: Optional[str] = Query(None),
    mobile: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
):
    pool = get_pool(request)
    offset = (page - 1) * limit
    user_id = user["sub"]

    rows = await pool.fetch(
        """
        SELECT DISTINCT r.id, r.qlik_app_id, r.qlik_sheet_id, r.title,
               r.description, r.category, r.tags, r.owner_name,
               r.data_sources, r.last_reload, r.is_active, r.created_at,
               COALESCE(r.is_mobile, FALSE) AS is_mobile,
               EXISTS(
                 SELECT 1 FROM user_preferences up
                 WHERE up.user_id = $1 AND r.id = ANY(up.pinned_reports)
               ) AS is_favorited
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.is_active = TRUE
          AND COALESCE(r.is_mobile, FALSE) = $2
          AND ($3::text IS NULL OR r.category = $3)
        ORDER BY r.category, r.title
        LIMIT $4 OFFSET $5
        """,
        user_id,
        mobile,
        category,
        limit,
        offset,
    )

    total = await pool.fetchval(
        """
        SELECT COUNT(DISTINCT r.id)
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.is_active = TRUE
          AND COALESCE(r.is_mobile, FALSE) = $2
          AND ($3::text IS NULL OR r.category = $3)
        """,
        user_id,
        mobile,
        category,
    )

    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"total": total, "page": page, "limit": limit},
    }


@router.get("/reports/trending")
async def trending_reports(
    request: Request,
    user: dict = Depends(require_user),
    mobile: bool = Query(False),
    limit: int = Query(6, ge=1, le=20),
):
    pool = get_pool(request)
    user_id = user["sub"]

    rows = await pool.fetch(
        """
        SELECT r.id, r.qlik_app_id, r.qlik_sheet_id, r.title,
               r.description, r.category, r.tags, r.owner_name,
               r.last_reload, COUNT(al.id) AS view_count
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        LEFT JOIN access_log al ON al.report_id = r.id
          AND al.accessed_at > NOW() - INTERVAL '7 days'
        WHERE r.is_active = TRUE
          AND COALESCE(r.is_mobile, FALSE) = $2
        GROUP BY r.id
        ORDER BY view_count DESC
        LIMIT $3
        """,
        user_id,
        mobile,
        limit,
    )

    return {"success": True, "data": [dict(r) for r in rows]}


@router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID,
    request: Request,
    user: dict = Depends(require_user),
):
    pool = get_pool(request)
    user_id = user["sub"]

    row = await pool.fetchrow(
        """
        SELECT DISTINCT r.*,
               EXISTS(
                 SELECT 1 FROM user_preferences up
                 WHERE up.user_id = $1 AND r.id = ANY(up.pinned_reports)
               ) AS is_favorited
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.id = $2 AND r.is_active = TRUE
        """,
        user_id,
        report_id,
    )

    if not row:
        return {"success": False, "error": "Report not found or access denied"}

    # Log access
    await pool.execute(
        "INSERT INTO access_log (user_id, report_id) VALUES ($1, $2)",
        user_id,
        report_id,
    )

    return {"success": True, "data": dict(row)}
