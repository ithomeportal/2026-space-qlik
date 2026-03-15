from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.routers.deps import get_pool, require_user

from app.config import settings

router = APIRouter(tags=["admin"])


async def require_admin(user: dict = Depends(require_user)) -> dict:
    """Verify user has admin role."""
    roles = user.get("roles", [])
    if "admin" not in roles:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# --- Reports CRUD ---


class ReportCreate(BaseModel):
    qlik_app_id: str
    qlik_sheet_id: str | None = None
    qlik_space_id: str | None = None
    title: str
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    owner_name: str | None = None
    data_sources: list[str] | None = None
    role_names: list[str] | None = None


class ReportRolesUpdate(BaseModel):
    role_names: list[str]


class ReportUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    owner_name: str | None = None
    data_sources: list[str] | None = None
    qlik_sheet_id: str | None = None
    is_active: bool | None = None


@router.get("/reports")
async def admin_list_reports(
    request: Request,
    _admin: dict = Depends(require_admin),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    pool = get_pool(request)
    offset = (page - 1) * limit

    rows = await pool.fetch(
        """
        SELECT r.*,
               COALESCE(
                 (SELECT COUNT(*) FROM access_log al WHERE al.report_id = r.id
                  AND al.accessed_at > NOW() - INTERVAL '30 days'), 0
               ) AS views_30d,
               ARRAY(
                 SELECT ro.name FROM roles ro
                 JOIN role_report_access rra ON rra.role_id = ro.id
                 WHERE rra.report_id = r.id
                 ORDER BY ro.name
               ) AS tag_roles
        FROM reports r
        ORDER BY r.title
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )

    total = await pool.fetchval("SELECT COUNT(*) FROM reports")

    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"total": total, "page": page, "limit": limit},
    }


@router.post("/reports")
async def admin_create_report(
    body: ReportCreate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)

    row = await pool.fetchrow(
        """
        INSERT INTO reports (qlik_app_id, qlik_sheet_id, qlik_space_id, title,
                             description, category, tags, owner_name, data_sources)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
        """,
        body.qlik_app_id,
        body.qlik_sheet_id,
        body.qlik_space_id,
        body.title,
        body.description,
        body.category,
        body.tags or [],
        body.owner_name,
        body.data_sources or [],
    )

    # Assign tag roles if provided
    if body.role_names:
        report_id = row["id"]
        for role_name in body.role_names:
            await pool.execute(
                """
                INSERT INTO role_report_access (role_id, report_id)
                SELECT id, $2 FROM roles WHERE name = $1
                ON CONFLICT DO NOTHING
                """,
                role_name,
                report_id,
            )

    return {"success": True, "data": dict(row)}


@router.patch("/reports/{report_id}")
async def admin_update_report(
    report_id: UUID,
    body: ReportUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"success": False, "error": "No fields to update"}

    set_clauses = []
    values = []
    for i, (key, val) in enumerate(updates.items(), start=2):
        set_clauses.append(f"{key} = ${i}")
        values.append(val)

    query = f"""
        UPDATE reports SET {', '.join(set_clauses)}, updated_at = NOW()
        WHERE id = $1
        RETURNING *
    """

    row = await pool.fetchrow(query, report_id, *values)
    if not row:
        return {"success": False, "error": "Report not found"}

    return {"success": True, "data": dict(row)}


@router.delete("/reports/{report_id}")
async def admin_delete_report(
    report_id: UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    await pool.execute(
        "UPDATE reports SET is_active = FALSE, updated_at = NOW() WHERE id = $1",
        report_id,
    )
    return {"success": True, "data": {"deleted": True}}


@router.patch("/reports/{report_id}/roles")
async def admin_update_report_roles(
    report_id: UUID,
    body: ReportRolesUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """Replace tag roles for a report."""
    pool = get_pool(request)
    await pool.execute(
        "DELETE FROM role_report_access WHERE report_id = $1", report_id
    )
    for role_name in body.role_names:
        await pool.execute(
            """
            INSERT INTO role_report_access (role_id, report_id)
            SELECT id, $2 FROM roles WHERE name = $1
            ON CONFLICT DO NOTHING
            """,
            role_name,
            report_id,
        )
    return {"success": True, "data": {"updated": True}}


# --- Roles CRUD ---


class RoleCreate(BaseModel):
    name: str
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    report_ids: list[UUID] | None = None


@router.get("/roles")
async def admin_list_roles(
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT r.*, (SELECT COUNT(*) FROM user_roles ur WHERE ur.role_id = r.id) AS user_count
        FROM roles r ORDER BY r.name
        """
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.post("/roles")
async def admin_create_role(
    body: RoleCreate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        "INSERT INTO roles (name, description) VALUES ($1, $2) RETURNING *",
        body.name,
        body.description,
    )
    return {"success": True, "data": dict(row)}


@router.patch("/roles/{role_id}")
async def admin_update_role(
    role_id: UUID,
    body: RoleUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)

    if body.name is not None:
        # Check uniqueness
        existing = await pool.fetchrow(
            "SELECT id FROM roles WHERE name = $1 AND id != $2",
            body.name,
            role_id,
        )
        if existing:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409, detail="A TagRole with that name already exists"
            )
        await pool.execute(
            "UPDATE roles SET name = $1 WHERE id = $2",
            body.name,
            role_id,
        )

    if body.description is not None:
        await pool.execute(
            "UPDATE roles SET description = $1 WHERE id = $2",
            body.description,
            role_id,
        )

    if body.report_ids is not None:
        await pool.execute(
            "DELETE FROM role_report_access WHERE role_id = $1", role_id
        )
        for report_id in body.report_ids:
            await pool.execute(
                "INSERT INTO role_report_access (role_id, report_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                role_id,
                report_id,
            )

    return {"success": True, "data": {"updated": True}}


@router.delete("/roles/{role_id}")
async def admin_delete_role(
    role_id: UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    await pool.execute("DELETE FROM roles WHERE id = $1", role_id)
    return {"success": True, "data": {"deleted": True}}


# --- Users ---


class UserRoleUpdate(BaseModel):
    role_ids: list[UUID]


@router.get("/users")
async def admin_list_users(
    request: Request,
    _admin: dict = Depends(require_admin),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    pool = get_pool(request)
    offset = (page - 1) * limit

    if search:
        rows = await pool.fetch(
            """
            SELECT u.*, ARRAY_AGG(r.name) FILTER (WHERE r.name IS NOT NULL) AS roles
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            LEFT JOIN roles r ON r.id = ur.role_id
            WHERE u.name ILIKE $1 OR u.email ILIKE $1
            GROUP BY u.id
            ORDER BY u.name
            LIMIT $2 OFFSET $3
            """,
            f"%{search}%",
            limit,
            offset,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT u.*, ARRAY_AGG(r.name) FILTER (WHERE r.name IS NOT NULL) AS roles
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            LEFT JOIN roles r ON r.id = ur.role_id
            GROUP BY u.id
            ORDER BY u.name
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    total = await pool.fetchval("SELECT COUNT(*) FROM users")
    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"total": total, "page": page, "limit": limit},
    }


@router.patch("/users/{user_id}")
async def admin_update_user_roles(
    user_id: UUID,
    body: UserRoleUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    await pool.execute("DELETE FROM user_roles WHERE user_id = $1", user_id)
    for role_id in body.role_ids:
        await pool.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id,
            role_id,
        )
    return {"success": True, "data": {"updated": True}}


# --- Apps CRUD ---


async def _fetch_favicon(url: str) -> str | None:
    """Fetch favicon for a URL and return as base64 data URI."""
    import base64

    import httpx

    try:
        domain = url.split("//")[-1].split("/")[0]
        favicon_url = (
            f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        )
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            resp = await client.get(favicon_url)
            # Google returns an image even on 404 (default globe icon)
            content_type = resp.headers.get("content-type", "")
            if "image" in content_type and len(resp.content) > 50:
                b64 = base64.b64encode(resp.content).decode()
                return f"data:{content_type};base64,{b64}"
    except Exception:
        pass
    return None


class AppCreate(BaseModel):
    title: str
    url: str
    description: str | None = None
    role_names: list[str] | None = None


class AppUpdate(BaseModel):
    title: str | None = None
    url: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AppRolesUpdate(BaseModel):
    role_names: list[str]


@router.get("/apps")
async def admin_list_apps(
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT a.*,
               ARRAY(
                 SELECT ro.name FROM roles ro
                 JOIN app_role_access ara ON ara.role_id = ro.id
                 WHERE ara.app_id = a.id
                 ORDER BY ro.name
               ) AS tag_roles
        FROM apps a
        ORDER BY a.title
        """
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.post("/apps")
async def admin_create_app(
    body: AppCreate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)

    # Fetch favicon and store as base64
    icon_data = await _fetch_favicon(body.url)

    row = await pool.fetchrow(
        """
        INSERT INTO apps (title, url, description, icon_data)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        body.title,
        body.url,
        body.description,
        icon_data,
    )

    if body.role_names:
        app_id = row["id"]
        for role_name in body.role_names:
            await pool.execute(
                """
                INSERT INTO app_role_access (role_id, app_id)
                SELECT id, $2 FROM roles WHERE name = $1
                ON CONFLICT DO NOTHING
                """,
                role_name,
                app_id,
            )

    return {"success": True, "data": dict(row)}


@router.patch("/apps/{app_id}")
async def admin_update_app(
    app_id: UUID,
    body: AppUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"success": False, "error": "No fields to update"}

    # Re-fetch favicon if URL changed
    if "url" in updates:
        icon_data = await _fetch_favicon(updates["url"])
        updates["icon_data"] = icon_data

    set_clauses = []
    values = []
    for i, (key, val) in enumerate(updates.items(), start=2):
        set_clauses.append(f"{key} = ${i}")
        values.append(val)

    query = f"""
        UPDATE apps SET {', '.join(set_clauses)}, updated_at = NOW()
        WHERE id = $1
        RETURNING *
    """
    row = await pool.fetchrow(query, app_id, *values)
    if not row:
        return {"success": False, "error": "App not found"}
    return {"success": True, "data": dict(row)}


@router.patch("/apps/{app_id}/roles")
async def admin_update_app_roles(
    app_id: UUID,
    body: AppRolesUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """Replace tag roles for an app."""
    pool = get_pool(request)
    await pool.execute(
        "DELETE FROM app_role_access WHERE app_id = $1", app_id
    )
    for role_name in body.role_names:
        await pool.execute(
            """
            INSERT INTO app_role_access (role_id, app_id)
            SELECT id, $2 FROM roles WHERE name = $1
            ON CONFLICT DO NOTHING
            """,
            role_name,
            app_id,
        )
    return {"success": True, "data": {"updated": True}}


@router.post("/apps/{app_id}/refresh-icon")
async def admin_refresh_app_icon(
    app_id: UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """Re-fetch favicon for an app."""
    pool = get_pool(request)
    row = await pool.fetchrow("SELECT url FROM apps WHERE id = $1", app_id)
    if not row:
        return {"success": False, "error": "App not found"}
    icon_data = await _fetch_favicon(row["url"])
    await pool.execute(
        "UPDATE apps SET icon_data = $1 WHERE id = $2", icon_data, app_id
    )
    return {"success": True, "data": {"refreshed": True, "has_icon": icon_data is not None}}


@router.delete("/apps/{app_id}")
async def admin_delete_app(
    app_id: UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    pool = get_pool(request)
    await pool.execute(
        "UPDATE apps SET is_active = FALSE, updated_at = NOW() WHERE id = $1",
        app_id,
    )
    return {"success": True, "data": {"deleted": True}}


# --- Seed ---


@router.post("/seed")
async def admin_seed(request: Request, secret: str = Query(...)):
    """Trigger database seed. Protected by secret query param."""
    if secret != settings.SEED_SECRET:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Invalid secret")

    from app.services.seed import seed_all

    await seed_all()
    return {"success": True, "data": {"seeded": True}}


@router.post("/sync-users")
async def admin_sync_users(_admin: dict = Depends(require_admin)):
    """Manually trigger user sync from time-off DB. Admin only."""
    from app.services.sync_users import sync_users

    result = await sync_users()
    return {"success": True, "data": result}


# --- Usage Analytics ---


@router.get("/usage")
async def admin_usage(
    request: Request,
    _admin: dict = Depends(require_admin),
    days: int = Query(30, ge=1, le=90),
):
    pool = get_pool(request)

    daily_views = await pool.fetch(
        """
        SELECT r.title, DATE(al.accessed_at) AS date, COUNT(*) AS views
        FROM access_log al
        JOIN reports r ON r.id = al.report_id
        WHERE al.accessed_at > NOW() - make_interval(days => $1)
        GROUP BY r.title, DATE(al.accessed_at)
        ORDER BY date DESC
        """,
        days,
    )

    top_reports = await pool.fetch(
        """
        SELECT r.title, r.category, COUNT(*) AS total_views,
               COUNT(DISTINCT al.user_id) AS unique_users
        FROM access_log al
        JOIN reports r ON r.id = al.report_id
        WHERE al.accessed_at > NOW() - make_interval(days => $1)
        GROUP BY r.id, r.title, r.category
        ORDER BY total_views DESC
        LIMIT 10
        """,
        days,
    )

    return {
        "success": True,
        "data": {
            "daily_views": [dict(r) for r in daily_views],
            "top_reports": [dict(r) for r in top_reports],
        },
    }
