# SPEC-QLIK: Qlik Embed Integration & JWT Setup

## 1. Embedding Approach

Use **`@qlik/embed-web-components`** (`<qlik-embed>`) — the official Qlik embedding library.

### Why NOT plain iframes:
- `/single/` iframe URLs require user to be already authenticated in Qlik Cloud (cookie-based)
- Break when third-party cookies are blocked (most modern browsers)
- No programmatic control over selections, bookmarks, responsive behavior
- `<qlik-embed>` wraps an iframe internally but handles auth transparently via JWT

### Component Usage:
```tsx
// components/QlikEmbed.tsx
import "@qlik/embed-web-components"

export function QlikEmbed({ appId, sheetId, qlikToken }: Props) {
  return (
    <qlik-embed
      ui="classic/app"
      app-id={appId}
      sheet-id={sheetId}
      auth-type="Jwt"
      jwt={qlikToken}
      style={{ width: "100%", height: "calc(100vh - 64px)" }}
    />
  )
}
```

### Embed Modes:
| Mode | Use Case |
|------|----------|
| `ui="classic/app"` | Full sheet embed with all Qlik interactions (primary mode) |
| `ui="classic/chart"` | Single chart/object embed (for preview panels) |
| `ui="analytics/sheet"` | New responsive sheet rendering (alternative) |

---

## 2. JWT Authentication Flow

### End-to-End Flow:
1. User logs into portal via NextAuth (email code)
2. Next.js calls `POST /api/qlik/token` on the FastAPI backend, passing user's session claims
3. FastAPI signs a Qlik-compatible JWT (RS256) with user's subject, groups, and custom attributes
4. JWT returned to browser, stored **in memory only** (not localStorage)
5. `<qlik-embed>` initialized with the JWT and the app GUID from the report catalog
6. Qlik Cloud validates JWT, applies RLS, renders the app inside the iframe
7. Frontend refreshes JWT every 50 minutes (before 60-min expiry)

### FastAPI JWT Generation:
```python
import jwt
import uuid
import time
from app.config import settings

def generate_qlik_jwt(user_sub: str, groups: list[str], attrs: dict) -> str:
    payload = {
        "sub": user_sub,
        "name": attrs.get("display_name"),
        "groups": groups,
        "jti": str(uuid.uuid4()),
        "iat": time.time(),
        "exp": time.time() + 3600,  # 60 minutes
        "iss": settings.QLIK_ISSUER,
        "aud": "qlik.api/login/jwt-session",
        **attrs  # company, region, cost_center for RLS
    }
    return jwt.encode(
        payload,
        settings.QLIK_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": settings.QLIK_KEY_ID}
    )
```

---

## 3. JWT Identity Provider Setup (REQUIRED — NOT YET DONE)

The `/api/v1/identity-providers` returned empty `[]`. This MUST be configured before embedding works.

### Step-by-Step:

#### 3.1. Generate RSA Key Pair
```bash
# Generate private key (keep secret — goes to Render env)
openssl genrsa -out qlik_private.pem 4096

# Extract public key (upload to Qlik Cloud)
openssl rsa -in qlik_private.pem -pubout -out qlik_public.pem

# Convert public key to JWK format (Qlik requires JWK, not PEM)
# Use a tool like https://pem-to-jwk.vercel.app or:
python3 -c "
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import json, base64

with open('qlik_public.pem', 'rb') as f:
    pub = serialization.load_pem_public_key(f.read(), backend=default_backend())
    nums = pub.public_numbers()

def int_to_base64url(n, length):
    return base64.urlsafe_b64encode(n.to_bytes(length, 'big')).rstrip(b'=').decode()

jwk = {
    'kty': 'RSA',
    'use': 'sig',
    'alg': 'RS256',
    'n': int_to_base64url(nums.n, 512),
    'e': int_to_base64url(nums.e, 3),
    'kid': 'analytics-hub-key-1'
}
print(json.dumps(jwk, indent=2))
"
```

#### 3.2. Register JWT IdP in Qlik Cloud via API
```bash
export QLIK_KEY="<bot-mcp API key>"

curl -X POST "https://mb01txe2h9rovgh.us.qlikcloud.com/api/v1/identity-providers" \
  -H "Authorization: Bearer $QLIK_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "external",
    "protocol": "jwtAuth",
    "interactive": false,
    "active": true,
    "description": "Analytics Hub Portal JWT",
    "options": {
      "jwtLoginEnabled": true,
      "issuer": "https://analytics-hub.unilinkportal.com",
      "staticKeys": [
        {
          "kid": "analytics-hub-key-1",
          "pem": "<contents of qlik_public.pem>"
        }
      ]
    }
  }'
```

#### 3.3. Store Configuration
After creation, note down:
- `issuer` → set as `QLIK_ISSUER` env var on Render
- `kid` → set as `QLIK_KEY_ID` env var on Render
- Private key PEM → set as `QLIK_PRIVATE_KEY` env var on Render

---

## 4. Lessons Learned from `/BOT/qlik-api`

### What Works for Embedding:
- KPI cards (`kpi`) — Most reliable single-object embed
- Tables (`sn-table`, `pivot-table`) — Work but need specific props
- Full sheets (`classic/app`) — Best for the portal use case

### What Doesn't Work:
- Bar/line charts via API creation often show blank
- Filter panes show "Incomplete visualization" when embedded individually
- `qlik-straight-table` is not available in Cloud SaaS

### Critical Tips:
1. **Number Formatting**: Always use `Num()` IN THE EXPRESSION, not `qNumFormat` property
2. **Table Props**: Every dimension/measure needs unique `cId`, `columnOrder`, `columnWidths`
3. **Publishing**: Objects in shared spaces are private by default — must be published + approved
4. **Space-qualified connections**: Use `'SpaceName:ConnectionName'` in load scripts
5. **Data model**: Fact tables with monthly pivot columns + lookup tables joined via customer_id
6. **Token refresh**: `<qlik-embed>` does NOT auto-refresh JWTs — the portal must handle this

---

## 5. Qlik Tenant Configuration

| Property | Value |
|----------|-------|
| Tenant URL | `https://mb01txe2h9rovgh.us.qlikcloud.com` |
| Alias URL | `https://unilink.us.qlikcloud.com` |
| Tenant ID | `ZC6dict00GLAZhISVRVWKm4d-l105j0n` |
| Admin | Diego Felipe Rodriguez (`dfrodriguez@unilinktransportation.com`) |
| API Key | `bot-mcp` (expires 2027-03-12) |
| JWT IdP | **NOT YET CONFIGURED** |
| Region | US |
