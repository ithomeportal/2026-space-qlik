from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_pool, require_user
from app.services.typesense_client import get_typesense_client

router = APIRouter(tags=["search"])


@router.get("/reports/search")
async def search_reports(
    request: Request,
    q: str = Query(..., min_length=1),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    user: dict = Depends(require_user),
    limit: int = Query(20, ge=1, le=50),
):
    pool = get_pool(request)
    user_id = user["sub"]

    # Get user's accessible report IDs
    accessible = await pool.fetch(
        """
        SELECT DISTINCT rra.report_id::text
        FROM role_report_access rra
        JOIN user_roles ur ON ur.role_id = rra.role_id
        WHERE ur.user_id = $1
        """,
        user_id,
    )
    accessible_ids = {r["report_id"] for r in accessible}

    if not accessible_ids:
        return {"success": True, "data": [], "meta": {"total": 0}}

    # Build Typesense search params
    client = get_typesense_client()
    search_params = {
        "q": q,
        "query_by": "title,description,tags,data_sources,owner_name",
        "per_page": limit,
    }

    filter_parts = []
    if category:
        filter_parts.append(f"category:={category}")
    if tags:
        filter_parts.append(f"tags:=[{tags}]")
    if filter_parts:
        search_params["filter_by"] = " && ".join(filter_parts)

    try:
        results = client.collections["reports"].documents.search(search_params)
    except Exception:
        # Fallback to database search if Typesense is unavailable
        return await _db_search(pool, q, user_id, category, limit)

    # Filter results by role access
    hits = []
    for hit in results.get("hits", []):
        doc = hit["document"]
        if doc["id"] in accessible_ids:
            hits.append(doc)

    return {
        "success": True,
        "data": hits,
        "meta": {"total": len(hits)},
    }


async def _db_search(pool, q: str, user_id, category, limit: int):
    """Fallback PostgreSQL search when Typesense is unavailable."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT r.id, r.qlik_app_id, r.qlik_sheet_id, r.title,
               r.description, r.category, r.tags, r.owner_name,
               r.data_sources, r.last_reload
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1
        WHERE r.is_active = TRUE
          AND (r.title ILIKE $2 OR r.description ILIKE $2
               OR $3 = ANY(r.tags))
          AND ($4::text IS NULL OR r.category = $4)
        LIMIT $5
        """,
        user_id,
        f"%{q}%",
        q.lower(),
        category,
        limit,
    )
    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"total": len(rows)},
    }
