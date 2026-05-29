"""Code-made report: Reports Index.

A leadership-only directory of every code-made report in the portal. Renders a
3-column catalog (name · summary+KPIs+audience · main link + related links).

Data source: ``analytics_hub`` (the primary pool via ``get_pool``) — this report
reads only portal metadata (`reports` + `role_report_access`), never a datalake.

Unlike the home grid (`/api/reports`, which role-filters to what the *viewer*
can open), this endpoint returns the FULL active catalog so directors/managers
get true discoverability. The Index itself is excluded from the listing.

The editorial "main KPIs" one-liner and "related reports" cross-links live in a
curated TS overlay on the frontend (`lib/reports-index-api.ts`), keyed by report
key. Everything else (title, description, note, category, tags, audience =
assigned TagRoles, main link = custom_path) is derived live from the catalog so
the Index can never go stale on names or paths.
"""

from fastapi import APIRouter, Depends, Request

from app.routers.deps import get_pool, require_report_access

router = APIRouter(tags=["reports-index"])

# This report's own key — excluded from the catalog it renders.
_INDEX_KEY = "reports-index"


@router.get("/custom/index/catalog")
async def index_catalog(
    request: Request,
    _user: dict = Depends(require_report_access(_INDEX_KEY)),
):
    """Return the full active code-made report catalog with assigned TagRoles.

    Each row carries the live metadata the Index needs; the frontend overlays
    the curated KPI line + related-report links by ``key``.
    """
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT r.title,
               r.description,
               r.note,
               r.category,
               r.tags,
               r.owner_name,
               r.custom_path,
               ARRAY(
                 SELECT ro.name FROM roles ro
                 JOIN role_report_access rra ON rra.role_id = ro.id
                 WHERE rra.report_id = r.id
                 ORDER BY ro.name
               ) AS tag_roles
        FROM reports r
        WHERE r.is_active = TRUE
          AND r.report_type = 'custom'
          AND r.custom_path IS DISTINCT FROM $1
        ORDER BY COALESCE(r.category, ''), r.title
        """,
        f"/reports/{_INDEX_KEY}",
    )

    data = []
    for r in rows:
        custom_path = r["custom_path"] or ""
        key = custom_path.replace("/reports/", "", 1)
        data.append(
            {
                "key": key,
                "title": r["title"],
                "description": r["description"],
                "note": r["note"],
                "category": r["category"],
                "tags": list(r["tags"] or []),
                "owner_name": r["owner_name"],
                "custom_path": custom_path,
                "tag_roles": list(r["tag_roles"] or []),
            }
        )

    return {"success": True, "data": data, "meta": {"total": len(data)}}
