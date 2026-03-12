# SPEC-ROADMAP: Implementation Roadmap & Success Metrics

## Phase 1 — MVP (Weeks 1–6)

| Week | Milestone | Deliverables |
|------|-----------|-------------|
| 1–2 | Auth + Skeleton | NextAuth email code integration, FastAPI scaffold, basic Next.js layout with header and grid placeholder, JWT IdP registration in Qlik Cloud |
| 3 | Report Catalog | PostgreSQL schema deployed on Aiven, admin seeding script (20 reports + roles + users), GET /api/reports with role filtering, report cards rendering in the grid |
| 4 | Qlik Embed | Qlik JWT flow end-to-end, `<qlik-embed>` component in /reports/[id], SSO working with test user, token refresh logic |
| 5 | Search | Typesense index populated from catalog, search bar with dropdown results, filter chips by category |
| 6 | Polish + QA | Favorites, pinned row, mobile responsive layout, loading skeletons, accessibility audit (WCAG AA), staging deployment |

## Phase 2 — Intelligence (Weeks 7–12)

- Semantic search via pgvector embeddings
- Claude API integration for natural language report summaries on hover
- Trending reports surfaced from access_log analytics
- Admin usage dashboard
- Report alert banners (admin-authored)
- Notification system for new report availability by role

## Phase 3 — Scale & Governance (Weeks 13–20)

- Qlik reload webhook → automatic last_reload metadata sync
- Request access flow: users can request access to reports outside their role
- Multi-language UI (i18n with next-intl)
- SSO to additional IdPs (Google Workspace, Okta)
- Performance optimization: edge caching of catalog on Vercel CDN
- Audit trail: every report view logged with timestamp and user for compliance

---

## Success Metrics & KPIs

| KPI | Target |
|-----|--------|
| Time-to-first-report | < 15 seconds from login to viewing a Qlik dashboard (vs. current ~3 min) |
| Search-to-result rate | > 85% of searches return a click within first 5 results |
| Report discovery | 3x more unique reports accessed per user vs. pre-portal baseline |
| Abandonment rate | < 10% of users who open the portal leave without viewing a report |
| Admin catalog coverage | 100% of active Qlik apps registered within 60 days of launch |
| Embed load time | Qlik iframe fully interactive in < 4 seconds on corporate network |
| User satisfaction (CSAT) | > 4.2/5 in quarterly internal UX survey |
| Zero auth complaints | 0 tickets/week about being prompted to log into Qlik separately |

---

## Infrastructure Deployment

### Frontend (Vercel)
- Auto-deploy from GitHub `main` branch
- Project: `ithome-7426` team
- Domain: TBD (e.g., `analytics.unilinkportal.com`)

### Backend (Render)
- FastAPI with Uvicorn
- Auto-deploy from GitHub
- Environment: Python 3.12+
- Typesense: Docker container on Render (or Typesense Cloud)

### Database (Aiven)
- Existing cluster: `pg-111cab4b-unlkdata.b.aivencloud.com:10261`
- New database: `analytics_hub`
- Enable pgvector extension for Phase 2

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| JWT IdP setup fails | Blocking — no embedding works | Have iframe fallback with cookie auth as backup |
| Qlik embed component CSP issues | Users see blank iframe | Test CSP headers early in Week 1; whitelist Qlik domains |
| Typesense Docker on Render costs | Budget overrun | Start with Typesense Cloud free tier (100K records) |
| 121 users × 20 reports = token storm | Qlik rate limits | Cache JWTs per user (60 min TTL), rate limit at proxy |
| Third-party cookie deprecation | `<qlik-embed>` breaks | Monitor Qlik's migration to OAuth/partition-based sessions |
| User adoption | Low usage | Run internal launch workshop; track abandonment; iterate on search |

---

## Lessons Learned (from /BOT/qlik-api project)

1. **Always use `Num()` in expressions** for number formatting — not property-level `qNumFormat`
2. **Objects in shared spaces are private by default** — must publish + approve for others to see
3. **Space-qualified connections**: Use `'SpaceName:ConnectionName'` format in load scripts
4. **The Developer role was deprecated end-of-2025** — use custom roles with "Manage API keys" permission
5. **API keys can silently stop working** if tenant settings change — always test with `/api/v1/users/me` first
6. **Mobile app copies are separate Qlik apps** — don't confuse them with the production versions
7. **Qlik Engine WebSocket (QIX)** is the only way to get sheet IDs programmatically — REST API doesn't expose them
8. **Publishing/approval workflow is critical** in shared spaces — unpublished objects are invisible to other users
