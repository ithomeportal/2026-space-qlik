"""AI chat tools — read-only, executed IN-PROCESS as the asking user.

Design (docs/SPEC-AI-CHAT.md, contract SPEC-CONTRACTS.md §3): the model never
touches SQL. It may only call five tools, and every report read is an
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
3. `section` must be in the section allowlist AND exist as a live GET route of
   that report; `params` must be query params THAT route declares, with bounded
   values (a list only where the route takes a list).

⚠ The proxy secret is attached ONLY to the in-process request headers; it never
enters a tool result, the model payload, a log line or the HTTP response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from types import UnionType
from typing import Any, Union, get_args, get_origin

import httpx
from fastapi.routing import APIRoute

from app.clock import CST, cst_today
from app.config import settings
from app.routers.deps import can_read_all_reports
from app.services import ai_chat_daily_brief as daily_brief
from app.services.seed import CUSTOM_REPORTS

logger = logging.getLogger(__name__)

# Every GET section of every readable report is decided ON PURPOSE: allowlisted
# here or listed in DENIED_SECTIONS (`test_every_readable_report_section_is_decided`
# fails on a new one). The first, 11-name list left most reports' real data —
# TEAM1 Direct Compare's /panel-summary among them — unreadable. Generated from the
# live route table 2026-10-17; each report's own gate still decides per user.
SECTION_ALLOWLIST = frozenset({
    "actuals", "actuals-by-lane", "all-orders", "annual", "attrition", "breakdown",
    "business-type-summary", "by-award-lane", "by-carrier-lane", "by-customer",
    "by-customer-award", "by-customer-detail", "by-customer-diff", "by-customer-lane-diff",
    "by-day", "by-department", "by-direction", "by-division", "by-hour", "by-job-title", "by-lane",
    "by-lane-diff", "by-month", "by-order", "by-team", "by-week", "carriers", "chart", 
    "combo", "concentration", "contract-spot", "contract-spot-kpis", "convertio-ratio", "cover",
    "cover-forecast", "customer-attrition", "customer-losses", "customer-overpay",
    "customer-spark", "customer-variance", "customers", "customers-margin", "daily",
    "data-freshness", "del/detail", "del/not-our-fault", "del/our-fault", "del/overview",
    "del/pinned", "details", "distribution", "exceptions", "facets", "filter-options",
    "filters", "freshness", "heatmap", "hold", "kpis", "lane-analysis", 
    "lane-summary", "lane-trend", "lanes", "lanes-margin", "loads", "loss-customers", "losses",
    "losses-by-month", "losses-by-week", "margin-distribution", "monthly", "monthly-totals",
    "months", "negative-orders", "note", "open-roles", "orders", "overview", "panel-summary",
    "pending-to-cover", "people-flow", "pipeline", "pivot", "podiums",
    "potential-by-month", "profit-tm-gauge", "projection", "pu/detail", "pu/not-our-fault",
    "pu/our-fault", "pu/overview", "pu/pinned", "rank", "rank/last-week", "reactive-summary",
    "risk", "service", "service-by-carrier", "service-incident-by-customer", "summary",
    "summary-by-customer", "summary-by-customer-detail", "summary-by-tab", "summary-table",
    "table", "team-performance", "team-performance-by-team", "team-projection",
    "team-projection-by-team", "team-projection-history", "team-projection-weekly",
    "team-variance", "team-variance-by-team", "team-variance-weekly", "team-weekly-performance",
    "teams-breakdown", "top-lanes-combo", "top5", "trend", "trend-12m", "trend-30d",
    "trend-daily", "trend-yoy", "trends", "trio-tables", "weekly", "weekly-movers",
    "weekly-performance", "weekly-trends", "workdays", "wow-variation", "activity",
    # Collections Settlement Forecast (2026-10-27): read-only cash in/out.
    "this-week", "weeks", "accuracy", "sources",
})
# Mail renderers, CSV exports, the admin EXPLAIN ANALYZE audit (runs the heaviest
# queries), per-person door scans, esavings `lane-rates` (a cache miss calls the paid
# SONAR / 123LB APIs per lane and UPSERTs — `equipment` is free text, so every call
# can miss), and the require_user-only call / ticket detail (other employees' free
# text and phone identifiers, company-wide). `.csv` exports are never allowlisted.
# Documentation for the decided-test; the gate itself is SECTION_ALLOWLIST alone.
DENIED_SECTIONS = frozenset({
    "digest-email", "team-digest-email", "delays-email", "explain", "rows",
    "lane-rates", "detail", "top-users", "pending", "closed",
    # customer-status-email: the rendered customer mail, and its config (addresses).
    "{key}/preview", "reports",
})
# `fresh` bypasses the cockpit cache and fans out to every tile endpoint.
DENIED_PARAMS = frozenset({"fresh"})
# Scope params a team clone (`…-t1`, `…-tm2`) accepts but IGNORES — it pins its team
# server-side. Offering them would let the model label TEAM1 numbers as TEAM2's.
_SCOPE_STEMS = ("division", "teams", "team", "sub_teams", "sub_team")
SCOPE_PARAMS = frozenset(
    stem if not period else f"{period}_{stem}" for stem in _SCOPE_STEMS for period in ("", "p1", "p2")
)
_TEAM_CLONE_SUFFIX = re.compile(r"-tm?[1-4]$")
# Door reports: no per-person attendance lookups through the assistant.
_ACCESS_DOORS_SUFFIX = "access-doors"
# Substrings of a report key OR its router prefix that are never offered.
DENIED_KEY_STEMS = ("payroll", "bonus", "division-payment", "admin-cashflow", "kam-performance")
TOOL_RESULT_MAX_CHARS = 6000
MAX_ABOUT_CHARS = 160
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
        "name": "list_report_sections",
        "description": (
            "The sections of one report you can read, each with the filter parameters it "
            "accepts and a one-line description. Call it before get_report_section when you "
            "do not already know the section and parameter names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"report_key": {"type": "string", "description": "A key from list_reports."}},
            "required": ["report_key"],
            "additionalProperties": False,
        },
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
                "section": {"type": "string", "description": "A section from list_report_sections."},
                "params": {
                    "type": "object",
                    "description": (
                        "Optional filters, named exactly as list_report_sections shows for this "
                        "section. Common ones: range (today|wtd|mtd|qtd|ytd), start_date / end_date "
                        "(YYYY-MM-DD), customer, limit (1-500). Period comparisons use p1_* / p2_*."
                    ),
                    "additionalProperties": {
                        "type": ["string", "integer", "number", "boolean", "array"],
                        "items": {"type": "string"},
                    },
                },
            },
            "required": ["report_key", "section"],
            "additionalProperties": False,
        },
    },
    {
        "name": "daily_brief",
        "description": (
            "Today's snapshot of every CORP team (TEAM1-TEAM4) this user can open, computed by "
            "the portal: MTD volume/revenue/operational gross profit/margin, avg_prof_day (AVG "
            "per day), projection, % of budget, today's profit, today's cover forecast, today's "
            "profit with forecast and its gap to avg_prof_day, budget variances, top 5 customer "
            "losses, pickup/delivery on-time %, and per-source freshness. For users who can "
            "open the division reports it also returns `divisions`: CORP (all CORP teams), DFW "
            "and TOTAL (CORP + DFW, summed by the portal) with the same fields; DFW has no "
            "budget, so its % of budget is null. Use it for 'how is the day looking', and for "
            "any question about today's profit (with forecast) or AVG per day of a team or "
            "division."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]
TOOL_NAMES = tuple(t["name"] for t in TOOL_DEFINITIONS)


class ToolInputError(ValueError):
    """The model asked for something outside the allowlists."""


# --------------------------------------------------------------------------
# Route table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteSpec:
    """A static GET route: its query params (name -> takes a list) and a one-line doc."""

    params: Mapping[str, bool]
    doc: str


_ROUTE_CACHE: weakref.WeakKeyDictionary[Any, dict[str, RouteSpec]] = weakref.WeakKeyDictionary()


def _is_list_annotation(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(_is_list_annotation(a) for a in get_args(annotation) if a is not type(None))
    return origin in (list, tuple, set, frozenset)


def _first_line(doc: str | None) -> str:
    line = (doc or "").strip().split("\n\n", 1)[0]
    line = " ".join(line.split())
    return line if len(line) <= MAX_ABOUT_CHARS else line[: MAX_ABOUT_CHARS - 1] + "…"


def get_route_table(app: Any) -> dict[str, RouteSpec]:
    """Every static GET path the app serves (no path parameters), with its query params."""
    cached = _ROUTE_CACHE.get(app)
    if cached is not None:
        return cached
    table = {
        r.path: RouteSpec(
            # The WIRE name: `date_from = Query(alias="from")` is sent as `from`.
            params={q.alias: _is_list_annotation(q.field_info.annotation) for q in r.dependant.query_params},
            doc=_first_line(r.description or getattr(r.endpoint, "__doc__", None)),
        )
        for r in app.routes
        if isinstance(r, APIRoute) and "GET" in (r.methods or set()) and "{" not in r.path
    }
    _ROUTE_CACHE[app] = table
    return table


def invalidate_route_cache() -> None:
    _ROUTE_CACHE.clear()


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _is_denied(*names: str) -> bool:
    return any(stem in name for name in names for stem in DENIED_KEY_STEMS)


def _clean_scalar(name: str, value: Any) -> str | int | float | bool:
    if not isinstance(value, str | int | float | bool):
        raise ToolInputError(f"param '{name}' must be a string, number or boolean")
    if isinstance(value, str) and len(value) > MAX_PARAM_CHARS:
        raise ToolInputError(f"param '{name}' is too long")
    return value


def _clean_limit(value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        raise ToolInputError(f"param 'limit' must be an integer 1-{MAX_LIMIT}")
    return value


def _refused_param(prefix: str, name: str) -> str | None:
    """Why the assistant may not pass ``name`` to this report, or None."""
    if name in DENIED_PARAMS:
        return f"param '{name}' is not available to the assistant"
    if name in SCOPE_PARAMS and _TEAM_CLONE_SUFFIX.search(prefix):
        return f"param '{name}' is locked by this team report — it always shows its own team"
    if name == "name" and prefix.endswith(_ACCESS_DOORS_SUFFIX):
        return "door reports cannot be filtered to one person by the assistant"
    return None


def offered_params(prefix: str, spec: RouteSpec) -> list[str]:
    return sorted(n for n in spec.params if _refused_param(prefix, n) is None)


def _clean_params(params: Any, spec: RouteSpec, prefix: str, where: str) -> dict[str, Any]:
    if params in (None, {}):
        return {}
    if not isinstance(params, dict):
        raise ToolInputError("params must be an object")
    clean: dict[str, Any] = {}
    for name, value in params.items():
        if name not in spec.params:
            raise ToolInputError(f"{where} does not take param '{name}' — see list_report_sections")
        if (refused := _refused_param(prefix, name)) is not None:
            raise ToolInputError(refused)
        if name == "limit":
            clean[name] = _clean_limit(value)
        elif isinstance(value, list):
            if not spec.params[name]:
                raise ToolInputError(f"param '{name}' takes one value, not a list")
            if len(value) > MAX_LIST_ITEMS:
                raise ToolInputError(f"param '{name}' has too many items")
            clean[name] = [_clean_scalar(name, v) for v in value]
        else:
            clean[name] = _clean_scalar(name, value)
    return clean


def _with_custom_ranges(clean: dict[str, Any], spec: RouteSpec) -> dict[str, Any]:
    """Dates count only under ``range=custom`` on nearly every report (any other range,
    or the default ``mtd``, silently wins). Fill it in, per period (``p1_``/``p2_``)."""
    filled = dict(clean)
    for period in ("", "p1_", "p2_"):
        range_key = f"{period}range"
        has_dates = any(f"{period}{k}" in clean for k in ("start_date", "end_date"))
        if not has_dates or range_key not in spec.params:
            continue
        given = clean.get(range_key)
        if given is None:
            filled[range_key] = "custom"
        elif given != "custom":
            raise ToolInputError(f"{period}start_date/{period}end_date need {range_key}=custom, not '{given}'")
    return filled


def _readable_prefix(report_key: Any, catalog_keys: frozenset[str]) -> str:
    if not isinstance(report_key, str) or report_key not in catalog_keys:
        raise ToolInputError("unknown report_key — use list_reports")
    prefix = REPORT_ROUTE_PREFIX.get(report_key, report_key)
    if _is_denied(report_key, prefix):
        raise ToolInputError(f"report {report_key} is not available to the assistant")
    if report_key == COCKPIT_KEY:
        # The raw summary carries tiles of denied reports; only the tool filters them.
        raise ToolInputError(f"use ceo_cockpit_summary for {COCKPIT_KEY}")
    return prefix


def validate_section_call(
    report_key: Any,
    section: Any,
    params: Any,
    *,
    catalog_keys: frozenset[str],
    get_paths: Mapping[str, RouteSpec],
) -> tuple[str, str, dict[str, Any]]:
    """Return (router_prefix, path, clean_params) or raise ToolInputError."""
    prefix = _readable_prefix(report_key, catalog_keys)
    if not isinstance(section, str) or section not in SECTION_ALLOWLIST:
        raise ToolInputError(f"section {section!r} is not readable — use list_report_sections")
    path = f"/api/custom/{prefix}/{section}"
    spec = get_paths.get(path)
    if spec is None:
        raise ToolInputError(f"section '{section}' is not available for {report_key} — use list_report_sections")
    clean = _clean_params(params, spec, prefix, f"{report_key}/{section}")
    return prefix, path, _with_custom_ranges(clean, spec)


def readable_sections(report_key: Any, *, catalog_keys: frozenset[str],
                      get_paths: Mapping[str, RouteSpec]) -> list[dict[str, Any]]:
    """[{section, params, about}] for every allowlisted live GET section of one report."""
    prefix = _readable_prefix(report_key, catalog_keys)
    base = f"/api/custom/{prefix}/"
    rows = []
    for path, spec in sorted(get_paths.items()):
        section = path[len(base):] if path.startswith(base) else ""
        if section in SECTION_ALLOWLIST:
            rows.append({"section": section, "params": offered_params(prefix, spec), "about": spec.doc})
    return rows


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


def answer_as_of(stamps: list[str | None], today: date) -> str | None:
    """The answer's age: the oldest stamp, floored at yesterday's close of day.

    Every report refreshes at least by each day's close (owner, 2026-10-17), so a
    report with no load stamp (None) is as of yesterday's close — and a stamp from
    today is no fresher than that floor for an answer built from several reports.
    A stamp OLDER than yesterday's close still wins: the floor never hides staleness.
    """
    if not stamps:
        return None
    close = today - timedelta(days=1)
    known = oldest_of(stamps)
    if None not in stamps:
        return known
    close_end = datetime.combine(today, time.min, tzinfo=CST)
    parsed = _parse_ts(known) if known else None
    return known if parsed is not None and parsed < close_end else close.isoformat()


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


def truncate(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    """Cap at ``limit`` and SAY so — the model must know the list is partial."""
    if len(text) <= limit:
        return text
    total = len(text)
    marker_len = len(f"…[truncated: showing the first {limit} chars of {total}]")
    kept = limit - marker_len
    return text[:kept] + f"…[truncated: showing the first {kept} chars of {total}]"


def _dump(value: Any, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    return truncate(json.dumps(value, default=str, separators=(",", ":"), ensure_ascii=False), limit)


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
    # The last daily_brief payload, so the route can return its scoreboard (contract §5).
    brief: dict | None = None
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
            if name == "daily_brief":
                return await self._daily_brief()
            args = tool_input if isinstance(tool_input, dict) else {}
            if name == "list_report_sections":
                return await self._sections(args.get("report_key"))
            return await self._section(args.get("report_key"), args.get("section"), args.get("params"))
        except ToolInputError as exc:
            return ToolOutcome(str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001 - one broken report must not 500 the answer
            logger.warning("ai-chat tool %s failed: %s", name, type(exc).__name__)
            return ToolOutcome(f"{name} unavailable ({type(exc).__name__})", is_error=True)

    def data_as_of(self) -> str | None:
        """Oldest freshness among reports USED; an unknown one counts as yesterday's close."""
        return answer_as_of([self.freshness.get(k) for k in self.reports_used], cst_today())

    # ---- access -----------------------------------------------------------

    async def _accessible_reports(self) -> dict[str, dict]:
        """key → {title, description} for reports this user may open (admin / CEO read
        all — ``can_read_all_reports``, the same rule as ``require_report_access``)."""
        async with self._lock:
            if self._accessible is None:
                roles = {str(r).lower() for r in (self.identity.get("roles") or [])}
                read_all = can_read_all_reports(roles)
                rows = await self.pool.fetch(ACCESSIBLE_REPORTS_SQL)
                accessible: dict[str, dict] = {}
                for row in rows:
                    key = (row["custom_path"] or "").replace("/reports/", "", 1)
                    granted = {str(r).lower() for r in (row["roles"] or [])}
                    if key and (read_all or roles & granted):
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

    async def _daily_brief(self) -> ToolOutcome:
        """Per-team snapshot (services/ai_chat_daily_brief.py). Its own, larger cap:
        four teams do not fit the generic 6000 chars."""
        accessible = await self._accessible_reports()
        results = await daily_brief.collect(self._get, accessible)
        for result in results:
            for key, fresh in result.used.items():
                self._mark_used(key, accessible[key]["title"])
                stamp = oldest_timestamp(fresh) if fresh is not None else None
                previous = self.freshness.get(key)
                self.freshness[key] = oldest_of([stamp, previous]) if previous else stamp
        payload = daily_brief.payload_of(results)
        self.brief = payload
        return ToolOutcome(_dump(payload, daily_brief.DAILY_BRIEF_MAX_CHARS))

    async def _sections(self, report_key: Any) -> ToolOutcome:
        rows = readable_sections(report_key, catalog_keys=CATALOG_KEYS, get_paths=get_route_table(self.app))
        accessible = await self._accessible_reports()
        if report_key not in accessible:
            return ToolOutcome(f"no access to {report_key}")
        return ToolOutcome(_dump({"report": report_key, "sections": rows}))

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
        if fresh is None:
            fresh = {"as_of": (cst_today() - timedelta(days=1)).isoformat(),
                     "basis": "no load stamp; reports refresh by each close of day"}
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
