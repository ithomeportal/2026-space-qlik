import typesense

from app.config import settings

_client = None


def get_typesense_client() -> typesense.Client:
    global _client
    if _client is None:
        _client = typesense.Client(
            {
                "api_key": settings.TYPESENSE_API_KEY,
                "nodes": [
                    {
                        "host": settings.TYPESENSE_HOST,
                        "port": settings.TYPESENSE_PORT,
                        "protocol": settings.TYPESENSE_PROTOCOL,
                    }
                ],
                "connection_timeout_seconds": 5,
            }
        )
    return _client


def init_reports_collection():
    """Create or update the reports collection schema."""
    client = get_typesense_client()

    schema = {
        "name": "reports",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "title", "type": "string", "sort": True},
            {"name": "description", "type": "string"},
            {"name": "category", "type": "string", "facet": True},
            {"name": "tags", "type": "string[]", "facet": True},
            {"name": "owner_name", "type": "string"},
            {"name": "data_sources", "type": "string[]"},
            {"name": "last_reload", "type": "int64", "sort": True},
        ],
        "default_sorting_field": "last_reload",
    }

    try:
        client.collections["reports"].retrieve()
    except typesense.exceptions.ObjectNotFound:
        client.collections.create(schema)
