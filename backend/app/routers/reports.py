from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_pool, require_user, user_uuid

router = APIRouter(tags=["reports"])


@router.get("/reports")
async def list_reports(
    request: Request,
    user: dict = Depends(require_user),
    category: Optional[str] = Query(None),
    mobile: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    pool = get_pool(request)
    offset = (page - 1) * limit
    user_id = user_uuid(user)

    rows = await pool.fetch(
        """
        SELECT DISTINCT r.id, r.title,
               r.description, r.note, r.category, r.tags, r.owner_name,
               r.data_sources, r.last_reload, r.is_active, r.created_at,
               r.report_type, r.custom_path,
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
          -- `mobile` INCLUDES the (Mob) variants, it does not replace the
          -- desktop set. `useIsMobile()` calls anything under 1920px mobile and
          -- every seeded report carries `is_mobile = FALSE`, so the old
          -- `= $2` equality made Home render "0 reports" on any laptop —
          -- silently, with no error anywhere. A duplicate tile is visible; a
          -- blank catalog is not.
          AND (COALESCE(r.is_mobile, FALSE) = FALSE OR $2)
          AND ($3::text IS NULL OR r.category = $3)
        -- Favourites first (Bruno PDF 2026-08-17 R3). This has to happen in SQL,
        -- not only in the grid: there are 60 reports and the default page size
        -- is 50, so a favourite sorted below the cut would never reach the
        -- client to be re-sorted.
        ORDER BY is_favorited DESC, view_count DESC, r.title
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
          AND (COALESCE(r.is_mobile, FALSE) = FALSE OR $2)
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


@router.get("/reports/access/{report_key}")
async def report_access(
    report_key: str,
    request: Request,
    user: dict = Depends(require_user),
):
    """Return whether the current user can view a code-made report and which TagRoles grant access.

    Powers the frontend ``<ReportGuard reportKey="..."/>`` so the access banner
    always reflects the live role list managed via ``/admin/reports``.
    """
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT ro.name
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN roles ro ON ro.id = rra.role_id
        WHERE r.custom_path = $1 AND r.is_active = TRUE
        ORDER BY ro.name
        """,
        f"/reports/{report_key}",
    )
    allowed_names = [r["name"] for r in rows]
    user_roles_lower = {r.lower() for r in user.get("roles", [])}
    is_admin = "admin" in user_roles_lower
    allowed_lower = {n.lower() for n in allowed_names}
    has_access = is_admin or bool(user_roles_lower & allowed_lower)
    # Hide internal singletons from the displayed banner so we don't tell users
    # to "ask for admin access".
    display_roles = [
        n for n in allowed_names if n.lower() not in ("admin", "super_admin")
    ]
    return {
        "success": True,
        "data": {
            "key": report_key,
            "allowed": has_access,
            "roles": display_roles,
        },
    }


@router.get("/reports/trending")
async def trending_reports(
    request: Request,
    user: dict = Depends(require_user),
    mobile: bool = Query(False),
    limit: int = Query(6, ge=1, le=20),
):
    pool = get_pool(request)
    user_id = user_uuid(user)

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
          -- Same inclusive rule as `list_reports` — see the note there.
          AND (COALESCE(r.is_mobile, FALSE) = FALSE OR $2)
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
    user_id = user_uuid(user)

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
    user_id = user_uuid(user)

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


@router.get("/user/favorites")
async def list_user_favorites(
    request: Request,
    user: dict = Depends(require_user),
    mobile: bool = Query(False),
):
    """The current user's starred reports, for the in-report Favorites rail.

    Powers ``<FavoritesSidebar/>`` — the collapsible left column every
    ``/reports/*`` route renders, so a user can jump between their favourites
    without going back Home (request 2026-09-09).

    Two invariants this endpoint exists to hold:

    * **It shows exactly what Home's "Favorites" filter shows.** The access
      gate is a byte-for-byte copy of ``list_reports``' — the same
      ``role_report_access``/``user_roles`` joins, the same ``is_active``, the
      same inclusive ``is_mobile`` clause. A user who was starred into a report
      and later lost the TagRole must drop out of BOTH, together. There is no
      admin bypass here for the same reason there is none on the Home list:
      the rail is a shortcut to what you can already see, not a second door.
    * **"Most used" means most used BY THIS USER.** ``access_log`` is counted
      with ``al.user_id = $1``. The Home grid's ``view_count`` is deliberately
      different — it is company-wide over 30 days, which orders every user's
      grid identically. A personal rail ordered by other people's habits would
      be indistinguishable from a broken one, so this is the one place the two
      orderings are allowed to disagree.

    All-time rather than a rolling window: a favourites list is a handful of
    rows, the ordering is stable, and a window would silently re-shuffle the
    rail for anyone back from leave. ``idx_access_log_user`` serves it.
    """
    pool = get_pool(request)
    user_id = user_uuid(user)

    rows = await pool.fetch(
        """
        SELECT DISTINCT r.id, r.title, r.category, r.custom_path,
               COALESCE(
                 (SELECT COUNT(*) FROM access_log al
                  WHERE al.report_id = r.id AND al.user_id = $1), 0
               ) AS use_count
        FROM reports r
        JOIN user_preferences up ON up.user_id = $1
          AND r.id = ANY(up.pinned_reports)
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.is_active = TRUE
          AND (COALESCE(r.is_mobile, FALSE) = FALSE OR $2)
        ORDER BY use_count DESC, r.title
        """,
        user_id,
        mobile,
    )

    return {"success": True, "data": [dict(r) for r in rows]}
