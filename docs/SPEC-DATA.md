# SPEC-DATA: Data Model & API Design

## 1. Database: PostgreSQL on Aiven

Connection: `pg-111cab4b-unlkdata.b.aivencloud.com:10261`
Create a NEW database (e.g., `analytics_hub`) on the existing Aiven cluster.

---

## 2. Core Tables

```sql
-- Reports catalog
CREATE TABLE reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  qlik_app_id     TEXT NOT NULL,
  qlik_sheet_id   TEXT,
  qlik_space_id   TEXT,
  title           TEXT NOT NULL,
  description     TEXT,
  category        TEXT,           -- Executive, Finance, Operations, Sales, HR, IT
  tags            TEXT[],
  owner_name      TEXT,
  data_sources     TEXT[],
  last_reload     TIMESTAMPTZ,
  embedding       vector(1536),   -- pgvector for semantic search (Phase 2)
  is_active       BOOLEAN DEFAULT TRUE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Roles
CREATE TABLE roles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT UNIQUE NOT NULL,  -- admin, executive, finance, etc.
  description     TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Role → Report mapping (many-to-many)
CREATE TABLE role_report_access (
  role_id         UUID REFERENCES roles(id) ON DELETE CASCADE,
  report_id       UUID REFERENCES reports(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, report_id)
);

-- Users
CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           TEXT UNIQUE NOT NULL,
  name            TEXT,
  department      TEXT,
  job_title       TEXT,
  company         TEXT,
  is_active       BOOLEAN DEFAULT TRUE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- User → Role mapping (many-to-many)
CREATE TABLE user_roles (
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  role_id         UUID REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

-- User preferences
CREATE TABLE user_preferences (
  user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  pinned_reports  UUID[],
  recent_reports  UUID[],
  theme           TEXT DEFAULT 'light'
);

-- Access log (for trending & usage analytics)
CREATE TABLE access_log (
  id              BIGSERIAL PRIMARY KEY,
  user_id         UUID REFERENCES users(id),
  report_id       UUID REFERENCES reports(id),
  accessed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_reports_category ON reports(category);
CREATE INDEX idx_reports_active ON reports(is_active);
CREATE INDEX idx_access_log_report ON access_log(report_id, accessed_at);
CREATE INDEX idx_access_log_user ON access_log(user_id, accessed_at);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active);
```

---

## 3. REST API Endpoints (FastAPI Backend)

### Public (authenticated user)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/reports` | Role-filtered report catalog for authenticated user |
| GET | `/api/reports/{id}` | Full metadata for a single report including AI summary |
| GET | `/api/reports/search` | Hybrid full-text + semantic search. Query params: `q`, `category`, `tags` |
| GET | `/api/reports/trending` | Top reports by access count in last 7 days, filtered by role |
| POST | `/api/qlik/token` | Generate a signed Qlik JWT for the current user session |
| GET | `/api/user/preferences` | Get pinned reports, recent history, theme |
| PATCH | `/api/user/preferences` | Update preferences (pin/unpin, theme) |

### Admin only
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/admin/reports` | Full unfiltered catalog with edit controls |
| POST | `/api/admin/reports` | Create a new report card in the catalog |
| PATCH | `/api/admin/reports/{id}` | Update report metadata |
| DELETE | `/api/admin/reports/{id}` | Soft-delete (sets is_active = false) |
| GET | `/api/admin/roles` | List all roles with user counts |
| POST | `/api/admin/roles` | Create a new role |
| PATCH | `/api/admin/roles/{id}` | Update role (add/remove reports) |
| DELETE | `/api/admin/roles/{id}` | Delete role (unassigns users) |
| GET | `/api/admin/users` | List all users with roles |
| PATCH | `/api/admin/users/{id}` | Update user roles |
| POST | `/api/admin/users/seed` | Seed users from time-off DB |
| GET | `/api/admin/usage` | Usage analytics — views per report, search queries, gaps |

---

## 4. API Response Format

```typescript
interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total: number
    page: number
    limit: number
  }
}
```

### Example: GET /api/reports
```json
{
  "success": true,
  "data": [
    {
      "id": "uuid-here",
      "title": "Executive Report",
      "description": "All-teams KPIs: revenue, loads, profit, margin",
      "category": "Executive",
      "tags": ["revenue", "profit", "margin", "loads"],
      "owner_name": "Melany",
      "last_reload": "2026-03-12T08:00:00Z",
      "qlik_app_id": "e4d975eb-e8ca-4727-8a9a-50db58907ef7",
      "qlik_sheet_id": "c77110fc-e146-4bbb-9d47-f534c2ac7803",
      "is_favorited": true
    }
  ],
  "meta": { "total": 12, "page": 1, "limit": 50 }
}
```

---

## 5. Next.js Backend Proxy

To avoid CORS issues, the Next.js app proxies requests to the FastAPI backend:

```typescript
// app/api/proxy/[...path]/route.ts
import { getServerSession } from "next-auth"

export async function GET(req: Request, { params }: { params: { path: string[] } }) {
  const session = await getServerSession(authOptions)
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 })

  const backendUrl = `${process.env.BACKEND_URL}/api/${params.path.join("/")}`
  const res = await fetch(backendUrl, {
    headers: {
      "Authorization": `Bearer ${session.accessToken}`,
      "Content-Type": "application/json"
    }
  })
  return Response.json(await res.json())
}
```
