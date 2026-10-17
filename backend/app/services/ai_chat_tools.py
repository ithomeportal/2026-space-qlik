"""AI chat tools — read-only, executed IN-PROCESS as the asking user.

Design (docs/SPEC-AI-CHAT.md, contract SPEC-CONTRACTS.md §3): the model never
touches SQL. It may only call three tools, and every report read is an
in-process GET to the report's OWN endpoint (httpx ASGITransport, the CEO
Cockpit technique §31) carrying the asking user's identity exactly as the
Vercel proxy would. So each report's `require_report_access` decides, numbers
are byte-identical to the report (KPI = detail §16), and a 403 becomes the tool
result "no access to <key>" instead of an exception.

Three gates before any call, all fail-closed:
1. `report_key` must be a seeded report (CUSTOM_REPORTS) and not a payroll /
   bonus / division-payment / admin-cashflow / KAM-performance report;
2. the user must GENUINELY hold access to that key (catalog check) — a borrowed
   endpoint (§52) would otherwise answer a scope-pinned SUBSET under a
   company-wide label, the exact trap the cockpit re-gates for;
3. `section` must be in the GET-only allowlist AND exist as a live GET route;
   `params` must be in the param allowlist with bounded scalar values.

⚠ The proxy secret is attached ONLY to the in-process request headers; it never
enters a tool result, the model payload, a log line or the HTTP response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from fastapi.routing import APIRoute

from app.clock import CST
from app.config import settings
from app.services.seed import CUSTOM_REPORTS

logger = logging.getLogger(__name__)

SECTION_ALLOWLIST = frozenset({
    "summary", "kpis", "freshness", "overview", "trends", "team-performance",
    "customer-variance", "weekly-trends", "by-customer", "by-team", "monthly",
})
PARAM_ALLOWLIST = frozenset({"range", "start_date", "end_date", "team", "teams", "customer", "limit"})
# Substrings of a report key OR its router prefix that are never offered.
DENIED_KEY_STEMS = ("payroll", "bonus", "division-payment", "admin-cashflow", "kam-performance")
TOOL_RESULT_MAX_CHARS = 6000
MAX_PARAM_CHARS = 100
MAX_LIST_ITEMS = 20
MAX_LIMIT = 500
INPROCESS_TIMEOUT_SECONDS = 45.0
COCKPIT_KEY = "ceo-cockpit"
COCKPIT_PATH = "/api/custom/ceo-cockpit/summary"
COCKPIT_TILE_FIELDS = ("key", "title", "category", "label", "value", "unit",
                       "baseline", "delta_abs", "delta_pct", "status", "as_of")

# Report key → live router prefix, where they differ. Verified against the
# route table 2026-10-17; `test_every_alias_targets_a_live_get_route` keeps it
# honest. Keys absent here use their own name as the prefix.
REPORT_ROUTE_PREFIX: dict[str, str] = {
    "esavings-carriers": "carriers-savings",
    "budget-followup-2026": "budget-followup",
    "xray-corp-mng": "xray-corp",
    "xray-dfw-mng": "xray-dfw",
    "carrier-sms-score": "carrier-sms",
    "it-tickets-mgmt": "it-tickets",
    "voip-calls-logs": "voip-calls",
    "ops-managers-portal-dfw": "ops-portal-overview-dfw",
    **{f"corp-t{n}-attrition-wow": f"attrition-wow-t{n}" for n in range(1, 5)},
    **{f"corp-t{n}-customer-score": f"ops-customer-score-t{n}" for n in range(1, 5)},
    **{f"corp-t{n}-direct-compare": f"ops-direct-compare-t{n}" for n in range(1, 5)},
    **{f"corp-t{n}-ops-kam-portal": f"ops-portal-overview-t{n}" for n in range(1, 5)},
}

CATALOG_KEYS = frozenset(r["key"] for r in CUSTOM_REPORTS)
_SEED_TITLES = {r["key"]: r["title"] for r in CUSTOM_REPORTS}

ACCESSIBLE_REPORTS_SQL = """
    SELECT r.custom_path, r.title, r.description,
           ARRAY(
             SELECT lower(ro.name)
               FROM role_report_access rra
               JOIN roles ro ON ro.id = rra.role_id
              WHERE rra.report_id = r.id
           ) AS roles
      FROM reports r
     WHERE r.is_active = TRUE
       AND r.report_type = 'custom'
"""

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_reports",
        "description": (
            "List the portal reports THIS user can open: key, title, short description. "
            "Call it first when you are unsure which report answers the question."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ceo_cockpit_summary",
        "description": (
            "The CEO Cockpit: one headline KPI per report (value, unit, status, delta, as-of). "
            "Best first stop for company-wide 'how are we doing' questions. Tiles with "
            "status 'locked' are reports this user cannot open."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_report_section",
        "description": (
            "Read one section of one report exactly as the report shows it. "
            "Returns the report's JSON (truncated to 6000 chars) plus its data freshness."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_key": {"type": "string", "description": "A key from list_reports."},
                "section": {"type": "string", "enum": sorted(SECTION_ALLOWLIST)},
                "params": {
                    "type": "object",
                    "description": (
                        "Optional filters: range (e.g. today|wtd|mtd|qtd|ytd), start_date / "
                        "end_date (YYYY-MM-DD), team, teams (list), customer, limit (1-500)."
                    ),
                    "properties": {
                        "range": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "team": {"type": "string"},
                        "teams": {"type": "array", "items": {"type": "string"}},
                        "customer": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["report_key", "section"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = tuple(t["name"] for t in TOOL_DEFINITIONS)


class ToolInputError(ValueError):
    """The model asked for something outside the allowlists."""


# --------------------------------------------------------------------------
# Route table
# --------------------------------------------------------------------------

_ROUTE_CACHE: weakref.WeakKeyDictionary[Any, frozenset[str]] = weakref.WeakKeyDictionary()


def get_route_table(app: Any) -> frozenset[str]:
    """Every static GET path the app serves (no path parameters)."""
    cached = _ROUTE_CACHE.get(app)
    if cached is not None:
        return cached
    paths = frozenset(
        r.path for r in app.routes
        if isinstance(r, APIRoute) and "GET" in (r.methods or set()) and "{" not in r.path
    )
    _ROUTE_CACHE[app] = paths
    return paths


def invalidate_route_cache() -> None:
    _ROUTE_CACHE.clear()


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _is_denied(*names: str) -> bool:
    return any(stem in name for name in names for stem in DENIED_KEY_STEMS)


def _clean_scalar(name: str, value: Any) -> str | int:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ToolInputError(f"param '{name}' must be a string or an integer")
    if isinstance(value, str) and len(value) > MAX_PARAM_CHARS:
        raise ToolInputError(f"param '{name}' is too long")
    return value


def _clean_limit(value: Any) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        raise ToolInputError(f"param 'limit' must be an integer 1-{MAX_LIMIT}")
    return value


def _clean_params(params: Any) -> dict[str, Any]:
    if params in (None, {}):
        return {}
    if not isinstance(params, dict):
        raise ToolInputError("params must be an object")
    clean: dict[str, Any] = {}
    for name, value in params.items():
        if name not in PARAM_ALLOWLIST:
            raise ToolInputError(f"param '{name}' is not allowed")
        if name == "limit":
            clean[name] = _clean_limit(value)
        elif name == "teams" and isinstance(value, list):
            if len(value) > MAX_LIST_ITEMS:
                raise ToolInputError("param 'teams' has too many items")
            clean[name] = [_clean_scalar(name, v) for v in value]
        else:
            clean[name] = _clean_scalar(name, value)
    return clean


def validate_section_call(
    report_key: Any,
    section: Any,
    params: Any,
    *,
    catalog_keys: frozenset[str],
    get_paths: frozenset[str],
) -> tuple[str, str, dict[str, Any]]:
    """Return (router_prefix, path, clean_params) or raise ToolInputError."""
    if not isinstance(report_key, str) or report_key not in catalog_keys:
        raise ToolInputError("unknown report_key — use list_reports")
    prefix = REPORT_ROUTE_PREFIX.get(report_key, report_key)
    if _is_denied(report_key, prefix):
        raise ToolInputError(f"report {report_key} is not available to the assistant")
    if not isinstance(section, str) or section not in SECTION_ALLOWLIST:
        raise ToolInputError(f"section must be one of: {', '.join(sorted(SECTION_ALLOWLIST))}")
    path = f"/api/custom/{prefix}/{section}"
    if path not in get_paths:
        raise ToolInputError(f"section '{section}' is not available for {report_key}")
    return prefix, path, _clean_params(params)


# --------------------------------------------------------------------------
# Freshness
# --------------------------------------------------------------------------

# The ONLY keys read as a load/refresh stamp. Taken from every live /freshness
# payload (2026-10-17). Business dates are NOT stamps and must never count:
# rfp-performance `min_date` is the first RFP ever, attrition-wow
# `last_load_date`, ops `last_created` / `last_pu` / `last_del` are events.
# hd-spot / production-spots-trends name feeds (`spot`, `gold`, `heartbeat`),
# exec-meeting-recruitment `tickets` / `people`, booker `sources[].updated_at`.
FRESHNESS_STAMP_KEYS = frozenset({
    "as_of", "last_updated", "updated_at", "refreshed_at", "loaded_at",
    "loads_updated", "loads_ts", "webhooks_received", "wh_ts", "received",
    "heartbeat", "spot", "gold", "tickets", "people",
})
# Containers never descended into (window bounds / bookkeeping).
_NOT_FRESHNESS_KEYS = frozenset({
    "window", "windows", "range", "period", "last_completed_week",
})


def _parse_ts(value: str) -> datetime | None:
    if len(value) < 10 or not value[:4].isdigit() or value[4] != "-":
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Naive stamps are read as CST (gold stores CST, §58); good enough to rank feeds.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=CST)


def oldest_of(values: Any) -> str | None:
    """The oldest parseable ISO stamp among ``values``, as printed; None if none parse."""
    parsed = [(ts, v) for v in values if isinstance(v, str) and (ts := _parse_ts(v)) is not None]
    return min(parsed)[1] if parsed else None


def oldest_timestamp(data: Any) -> str | None:
    """The STALEST load stamp in a /freshness payload (§54), as the report printed it."""
    stamps: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _NOT_FRESHNESS_KEYS:
                    continue
                if isinstance(value, str):
                    if key in FRESHNESS_STAMP_KEYS:
                        stamps.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return oldest_of(stamps)


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def truncate(text: str) -> str:
    """Cap at TOOL_RESULT_MAX_CHARS and SAY so — the model must know the list is partial."""
    limit = TOOL_RESULT_MAX_CHARS
    if len(text) <= limit:
        return text
    total = len(text)
    marker_len = len(f"…[truncated: showing the first {limit} chars of {total}]")
    kept = limit - marker_len
    return text[:kept] + f"…[truncated: showing the first {kept} chars of {total}]"


def _dump(value: Any) -> str:
    return truncate(json.dumps(value, default=str, separators=(",", ":"), ensure_ascii=False))


def _forward_headers(identity: dict) -> dict[str, str]:
    """Exactly what the Vercel proxy sends (frontend/app/api/proxy/[...path]/route.ts)."""
    shaped = {k: identity.get(k) for k in ("sub", "email", "name", "roles", "department", "company")}
    headers = {"authorization": "Bearer " + json.dumps(shaped), "content-type": "application/json"}
    if settings.PROXY_SHARED_SECRET:
        headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    return headers


def open_inprocess_client(app: Any) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://ai-chat.internal",
                             timeout=INPROCESS_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    is_error: bool = False


@dataclass
class ToolSession:
    """Per-request tool state: which reports were used and how fresh they are."""

    app: Any
    identity: dict
    pool: Any
    client: httpx.AsyncClient
    tools_used: list[str] = field(default_factory=list)
    reports_used: dict[str, dict] = field(default_factory=dict)
    freshness: dict[str, str | None] = field(default_factory=dict)
    _accessible: dict[str, dict] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---- public -----------------------------------------------------------

    async def execute(self, name: str, tool_input: Any) -> ToolOutcome:
        if name not in TOOL_NAMES:
            return ToolOutcome(f"unknown tool '{name}'", is_error=True)
        if name not in self.tools_used:
            self.tools_used.append(name)
        try:
            if name == "list_reports":
                return await self._list_reports()
            if name == "ceo_cockpit_summary":
                return await self._cockpit()
            args = tool_input if isinstance(tool_input, dict) else {}
            return await self._section(args.get("report_key"), args.get("section"), args.get("params"))
        except ToolInputError as exc:
            return ToolOutcome(str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001 - one broken report must not 500 the answer
            logger.warning("ai-chat tool %s failed: %s", name, type(exc).__name__)
            return ToolOutcome(f"{name} unavailable ({type(exc).__name__})", is_error=True)

    def data_as_of(self) -> str | None:
        """Oldest freshness among reports USED; None when any of them is unknown.

        An unknown age must not borrow another report's (fresher) time.
        """
        if not self.reports_used:
            return None
        stamps = [self.freshness.get(k) for k in self.reports_used]
        if any(s is None for s in stamps):
            return None
        return oldest_of(stamps)

    # ---- access -----------------------------------------------------------

    async def _accessible_reports(self) -> dict[str, dict]:
        """key → {title, description} for reports this user may open (admin bypasses)."""
        async with self._lock:
            if self._accessible is None:
                roles = {str(r).lower() for r in (self.identity.get("roles") or [])}
                is_admin = "admin" in roles
                rows = await self.pool.fetch(ACCESSIBLE_REPORTS_SQL)
                accessible: dict[str, dict] = {}
                for row in rows:
                    key = (row["custom_path"] or "").replace("/reports/", "", 1)
                    granted = {str(r).lower() for r in (row["roles"] or [])}
                    if key and (is_admin or roles & granted):
                        accessible[key] = {"title": row["title"], "description": row["description"]}
                self._accessible = accessible
            return self._accessible

    def _mark_used(self, key: str, title: str | None) -> None:
        self.reports_used.setdefault(
            key, {"key": key, "title": title or _SEED_TITLES.get(key, key), "path": f"/reports/{key}"}
        )

    # ---- tools ------------------------------------------------------------

    async def _list_reports(self) -> ToolOutcome:
        accessible = await self._accessible_reports()
        rows = [
            {"key": k, "title": v["title"], "description": v["description"]}
            for k, v in sorted(accessible.items())
            if k in CATALOG_KEYS and not _is_denied(k, REPORT_ROUTE_PREFIX.get(k, k))
        ]
        return ToolOutcome(_dump(rows))

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        # httpx does not enforce timeouts on ASGITransport — bound it ourselves.
        return await asyncio.wait_for(
            self.client.get(path, params=params or None, headers=_forward_headers(self.identity)),
            timeout=INPROCESS_TIMEOUT_SECONDS,
        )

    async def _cockpit(self) -> ToolOutcome:
        accessible = await self._accessible_reports()
        if COCKPIT_KEY not in accessible:
            return ToolOutcome(f"no access to {COCKPIT_KEY}")
        resp = await self._get(COCKPIT_PATH)
        if resp.status_code == 403:
            return ToolOutcome(f"no access to {COCKPIT_KEY}")
        if resp.status_code != 200:
            return ToolOutcome(f"{COCKPIT_KEY} unavailable (HTTP {resp.status_code})", is_error=True)
        data = (resp.json() or {}).get("data") or {}
        # The cockpit carries tiles of reports the assistant must never read
        # (e.g. admin-cashflow "Total Unbilled $"); drop them, like list_reports.
        tiles = [
            {f: t.get(f) for f in COCKPIT_TILE_FIELDS}
            for t in data.get("tiles") or []
            if not _is_denied(str(t.get("key")), REPORT_ROUTE_PREFIX.get(str(t.get("key")), ""))
        ]
        self._mark_used(COCKPIT_KEY, accessible[COCKPIT_KEY]["title"])
        # No /freshness on the cockpit: its oldest tile as_of stands in.
        tile_age = oldest_of(t.get("as_of") for t in tiles)
        previous = self.freshness.get(COCKPIT_KEY)
        self.freshness[COCKPIT_KEY] = oldest_of([tile_age, previous]) if previous else tile_age
        return ToolOutcome(_dump({"generated_at": data.get("generated_at"), "tiles": tiles}))

    async def _section(self, report_key: Any, section: Any, params: Any) -> ToolOutcome:
        prefix, path, clean = validate_section_call(
            report_key, section, params,
            catalog_keys=CATALOG_KEYS, get_paths=get_route_table(self.app),
        )
        accessible = await self._accessible_reports()
        if report_key not in accessible:
            return ToolOutcome(f"no access to {report_key}")
        resp = await self._get(path, clean)
        if resp.status_code == 403:
            return ToolOutcome(f"no access to {report_key}")
        if resp.status_code == 422:
            return ToolOutcome(f"invalid parameters for {report_key}/{section}: {resp.text[:300]}",
                               is_error=True)
        if resp.status_code != 200:
            return ToolOutcome(f"{report_key}/{section} unavailable (HTTP {resp.status_code})",
                               is_error=True)
        body = resp.json()
        result = {k: v for k, v in body.items() if k != "success"} if isinstance(body, dict) else body
        self._mark_used(report_key, accessible[report_key]["title"])
        fresh = await self._freshness(report_key, prefix, section, body)
        return ToolOutcome(_dump({
            "report": report_key, "section": section, "params": clean,
            "result": result, "freshness": fresh,
        }))

    async def _freshness(self, key: str, prefix: str, section: str, body: Any) -> Any:
        """The report's own /freshness payload (once per report); records its stalest stamp."""
        if section == "freshness":
            data = body.get("data", body) if isinstance(body, dict) else body
        else:
            path = f"/api/custom/{prefix}/freshness"
            if path not in get_route_table(self.app):
                self.freshness.setdefault(key, None)
                return None
            if key in self.freshness:
                return {"as_of": self.freshness[key]}
            try:
                resp = await self._get(path)
            except httpx.HTTPError:
                resp = None
            if resp is None or resp.status_code != 200:
                self.freshness[key] = None
                return None
            payload = resp.json()
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
        self.freshness[key] = oldest_timestamp(data)
        return data
