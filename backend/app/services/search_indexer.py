"""Index reports into Typesense for full-text search."""

import asyncpg

from app.config import settings
from app.services.typesense_client import get_typesense_client, init_reports_collection


async def index_all_reports():
    """Fetch all active reports from DB and index into Typesense."""
    init_reports_collection()
    client = get_typesense_client()

    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)

    try:
        rows = await pool.fetch(
            """
            SELECT id::text, title, COALESCE(description, '') AS description,
                   COALESCE(category, '') AS category,
                   COALESCE(tags, '{}') AS tags,
                   COALESCE(owner_name, '') AS owner_name,
                   COALESCE(data_sources, '{}') AS data_sources,
                   COALESCE(EXTRACT(EPOCH FROM last_reload)::bigint, 0) AS last_reload
            FROM reports
            WHERE is_active = TRUE
            """
        )

        documents = []
        for row in rows:
            documents.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"],
                    "category": row["category"],
                    "tags": list(row["tags"]),
                    "owner_name": row["owner_name"],
                    "data_sources": list(row["data_sources"]),
                    "last_reload": row["last_reload"],
                }
            )

        if documents:
            # Upsert all documents
            client.collections["reports"].documents.import_(
                documents, {"action": "upsert"}
            )

        return len(documents)

    finally:
        await pool.close()


if __name__ == "__main__":
    import asyncio

    count = asyncio.run(index_all_reports())
    print(f"Indexed {count} reports into Typesense")
