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
               r.description, r.note, r.category, r.tags, r.owner_name,
               r.data_sources, r.last_reload, r.is_active, r.created_at,
               COALESCE(r.is_mobile, FALSE) AS is_mobile,
               EXISTS(
                 SELECT 1 FROM user_preferences up
                 WHERE up.user_id = $1 AND r.id = ANY(up.pinned_reports)
               ) AS is_favorited,
               ARRAY(
                 SELECT ro.name FROM roles ro
                 JOIN role_report_access rra2 ON rra2.role_id = ro.id
                 WHERE rra2.report_id = r.id
                 ORDER BY ro.name
               ) AS tag_roles,
               COALESCE(
                 (SELECT COUNT(*) FROM access_log al WHERE al.report_id = r.id
                  AND al.accessed_at > NOW() - INTERVAL '30 days'), 0
               ) AS view_count
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.is_active = TRUE
          AND COALESCE(r.is_mobile, FALSE) = $2
          AND ($3::text IS NULL OR r.category = $3)
        ORDER BY view_count DESC, r.title
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


@router.get("/apps")
async def list_apps(
    request: Request,
    user: dict = Depends(require_user),
):
    """List ALL active apps — apps are visible to all authenticated users."""
    pool = get_pool(request)

    rows = await pool.fetch(
        """
        SELECT a.id, a.title, a.url, a.description,
               a.icon_data, a.is_active, a.created_at
        FROM apps a
        WHERE a.is_active = TRUE
        ORDER BY a.title
        """
    )

    return {
        "success": True,
        "data": [dict(r) for r in rows],
    }


@router.get("/user/tag-roles")
async def list_user_tag_roles(
    request: Request,
    user: dict = Depends(require_user),
):
    """Return TagRoles assigned to the current user, with report count per role."""
    pool = get_pool(request)
    user_id = user["sub"]

    rows = await pool.fetch(
        """
        SELECT r.id, r.name, r.description,
               (SELECT COUNT(DISTINCT rra.report_id)
                FROM role_report_access rra
                JOIN reports rep ON rep.id = rra.report_id AND rep.is_active = TRUE
                WHERE rra.role_id = r.id
               ) AS report_count
        FROM roles r
        JOIN user_roles ur ON ur.role_id = r.id AND ur.user_id = $1
        WHERE r.name != 'admin'
        ORDER BY report_count DESC, r.name
        """,
        user_id,
    )

    return {
        "success": True,
        "data": [dict(r) for r in rows],
    }
