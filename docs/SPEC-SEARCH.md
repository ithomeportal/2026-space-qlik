# SPEC-SEARCH: Search Engine & AI Features

## 1. Phase 1: Full-Text Search (Typesense)

### Why Typesense:
- Free and open source (vs Algolia paid)
- Sub-10ms full-text search
- Docker-deployable on Render
- Typo tolerance, faceting, geo-search built-in

### Typesense Collection Schema:
```json
{
  "name": "reports",
  "fields": [
    { "name": "id", "type": "string" },
    { "name": "title", "type": "string", "sort": true },
    { "name": "description", "type": "string" },
    { "name": "category", "type": "string", "facet": true },
    { "name": "tags", "type": "string[]", "facet": true },
    { "name": "owner_name", "type": "string" },
    { "name": "data_sources", "type": "string[]" },
    { "name": "last_reload", "type": "int64", "sort": true }
  ],
  "default_sorting_field": "last_reload"
}
```

### Search Features:
| Feature | Priority | Implementation |
|---------|----------|---------------|
| Full-text Search | Must Have | Searches title, description, tags, data sources, owner name |
| Instant Results Dropdown | Must Have | Results in floating panel within 150ms |
| Tag & Filter Chips | Must Have | Category, business unit, data freshness, favorites |
| Trending & Recent | Should Have | Show when search bar focused but empty |

### cmdk Integration:
```tsx
// components/SearchBar.tsx
import { Command } from "cmdk"

export function SearchBar() {
  return (
    <Command>
      <Command.Input placeholder="Search reports, KPIs, departments..." />
      <Command.List>
        <Command.Empty>No results found.</Command.Empty>
        <Command.Group heading="Recent">
          {recentReports.map(r => <ReportResult key={r.id} report={r} />)}
        </Command.Group>
        <Command.Group heading="Results">
          {searchResults.map(r => <ReportResult key={r.id} report={r} />)}
        </Command.Group>
      </Command.List>
    </Command>
  )
}
```

---

## 2. Phase 2: AI Semantic Search (pgvector + Anthropic)

### Why Semantic Search:
Users think in business terms: "How much we sold in Mexico last month" — not "Revenue_MX_Monthly_v3". Keyword search fails here. Vector embeddings bridge the gap.

### Implementation:
| Component | Detail |
|-----------|--------|
| Embedding Model | Anthropic's embeddings API — 1536-dimensional vectors |
| Storage | pgvector extension on PostgreSQL (Aiven) |
| Query Flow | User query → embed via API → cosine similarity in pgvector → top-K reports |
| Hybrid Search | Combine BM25 (Typesense) and semantic (pgvector) scores with weighted sum |
| Re-ranking | Optionally pass top-20 to Claude API for context-aware re-ranking |
| Cost | ~$0.0001/query at 1000 users/day = ~$3/month |

### Embedding Pipeline:
```python
# Run once per report (and on catalog updates)
import anthropic

client = anthropic.Anthropic()

def embed_report(report):
    text = f"{report.title} {report.description} {' '.join(report.tags)}"
    response = client.embeddings.create(
        model="voyage-3",
        input=[text]
    )
    return response.data[0].embedding  # 1536-dim vector
```

### Search Query:
```sql
-- Semantic search
SELECT id, title, description, category,
       1 - (embedding <=> $1::vector) AS similarity
FROM reports
WHERE is_active = TRUE
ORDER BY embedding <=> $1::vector
LIMIT 10;
```

---

## 3. Phase 2: Natural Language Report Summaries

When a user hovers a card or opens the quick-view drawer, the portal can call the Claude API to generate a plain-language summary.

```python
async def generate_report_summary(report: ReportMetadata) -> str:
    prompt = f"""You are a data analyst assistant. Given this report metadata:
    Title: {report.title}
    Category: {report.category}
    Description: {report.description}
    Data sources: {report.data_sources}
    Last refreshed: {report.last_reload}

    Write a 2-sentence plain-language summary for a business user.
    Focus on: what question it answers, and who should use it."""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text
```

Cache summaries in the reports table (`ai_summary` TEXT column) to avoid repeated API calls.
