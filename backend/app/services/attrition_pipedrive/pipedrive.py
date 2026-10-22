"""The slice of the Pipedrive API this job needs — reads on v1, writes on v2.

Same conventions as ``/BOT/seamless-pipedrive`` (``src/pipedrive/client.ts``):

* The token travels in the ``x-api-token`` HEADER (never the URL, so no httpx
  request log can print it); errors carry the method and PATH only.
* Pipeline, stage, users and custom-field keys are resolved BY NAME (users by
  login e-mail) at the start of a run and FAIL CLOSED. Field keys are 40-char
  hashes that differ per account; a wrong one is a write that succeeds and
  silently drops the value.
* Stage and pipeline are sent explicitly — a pipeline default is a UI setting
  somebody can change.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.services.attrition_pipedrive import config as cfg

logger = logging.getLogger(__name__)

TIMEOUT_S = 30.0


class PipedriveError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class PipedriveConfigError(PipedriveError):
    """A name the job depends on did not resolve — nothing is written."""


@dataclass(frozen=True)
class Placement:
    pipeline_id: int
    stage_id: int
    users: dict[str, int]                 # login e-mail (lower) → user id
    user_names: dict[int, str]            # user id → display name
    deal_reactivation_key: str
    deal_reactivation_option: int
    deal_mcleod_key: str
    org_mcleod_key: str


@dataclass(frozen=True)
class Deal:
    id: int
    title: str
    owner_id: Optional[int]
    org_id: Optional[int]
    pipeline_id: Optional[int]
    status: str


def normalize_name(name: str) -> str:
    """Upper-case, single-spaced, trailing punctuation dropped — for exact comparison."""
    return re.sub(r"\s+", " ", (name or "").upper()).strip().rstrip(".,").strip()


class PipedriveClient:
    def __init__(self, domain: str, token: str, http: Optional[httpx.AsyncClient] = None):
        if not domain or not token:
            raise PipedriveConfigError("PIPEDRIVE_DOMAIN / PIPEDRIVE_API_TOKEN not set")
        self._base = f"https://{domain}.pipedrive.com/api"
        self._token = token
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT_S)
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _request(
        self, method: str, version: str, path: str,
        params: Optional[dict[str, Any]] = None, body: Optional[dict[str, Any]] = None,
    ) -> Any:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            resp = await self._http.request(
                method, f"{self._base}/{version}/{path}", params=query, json=body,
                headers={"x-api-token": self._token},
            )
        except httpx.HTTPError as e:
            raise PipedriveError(f"{method} /{version}/{path}: {type(e).__name__}") from None
        if resp.status_code >= 400:
            raise PipedriveError(
                f"{method} /{version}/{path} returned HTTP {resp.status_code}", resp.status_code,
            )
        payload = resp.json()
        if payload.get("success") is False:
            raise PipedriveError(f"{method} /{version}/{path}: {payload.get('error') or 'unsuccessful'}")
        return payload.get("data")

    # ---- resolution (fail closed) ----------------------------------------

    async def resolve(self) -> Placement:
        pipelines = await self._request("GET", "v1", "pipelines") or []
        pipeline = _one(pipelines, "name", cfg.PIPELINE_NAME, "pipeline")
        stages = await self._request("GET", "v1", "stages", {"pipeline_id": pipeline["id"]}) or []
        stage = _one(stages, "name", cfg.STAGE_NAME, "stage")

        users = await self._request("GET", "v1", "users") or []
        by_email = {
            (u.get("email") or "").lower(): u for u in users if u.get("active_flag")
        }
        missing = [e for e in cfg.REQUIRED_USER_EMAILS if e not in by_email]
        if missing:
            raise PipedriveConfigError(f"Pipedrive users not active: {', '.join(missing)}")

        deal_fields = await self._request("GET", "v1", "dealFields", {"limit": 500}) or []
        react = _one(deal_fields, "name", cfg.DEAL_FIELD_REACTIVATION, "deal field")
        option = _one(react.get("options") or [], "label", cfg.DEAL_FIELD_REACTIVATION_OPTION,
                      "deal field option")
        deal_mcleod = _one(deal_fields, "name", cfg.FIELD_MCLEOD, "deal field")
        org_fields = await self._request("GET", "v1", "organizationFields", {"limit": 500}) or []
        org_mcleod = _one(org_fields, "name", cfg.FIELD_MCLEOD, "organization field")

        return Placement(
            pipeline_id=int(pipeline["id"]),
            stage_id=int(stage["id"]),
            users={e: int(u["id"]) for e, u in by_email.items() if e in cfg.REQUIRED_USER_EMAILS},
            user_names={int(u["id"]): u.get("name") or "" for u in users},
            deal_reactivation_key=react["key"],
            deal_reactivation_option=int(option["id"]),
            deal_mcleod_key=deal_mcleod["key"],
            org_mcleod_key=org_mcleod["key"],
        )

    # ---- organizations --------------------------------------------------

    async def _search_orgs(self, term: str, fields: str) -> list[dict]:
        data = await self._request(
            "GET", "v2", "organizations/search",
            {"term": term, "fields": fields, "exact_match": "true", "limit": 10},
        ) or {}
        return [i["item"] for i in data.get("items") or [] if i.get("item")]

    async def find_org(self, p: Placement, customer: str, mcleod_ids: tuple[str, ...]) -> Optional[int]:
        """McLeod code first (``ID_McLeod``, verified on the record), then exact name."""
        for code in mcleod_ids:
            for item in await self._search_orgs(code, "custom_fields"):
                org = await self._request("GET", "v2", f"organizations/{item['id']}") or {}
                value = (org.get("custom_fields") or {}).get(p.org_mcleod_key)
                if isinstance(value, str) and value.strip().upper() == code.upper():
                    return int(org["id"])
        wanted = normalize_name(customer)
        hits = [i for i in await self._search_orgs(customer, "name")
                if normalize_name(i.get("name") or "") == wanted]
        return min(int(i["id"]) for i in hits) if hits else None

    async def create_org(self, p: Placement, name: str, owner_id: int, mcleod_id: Optional[str]) -> int:
        body: dict[str, Any] = {"name": name, "owner_id": owner_id}
        if mcleod_id:
            body["custom_fields"] = {p.org_mcleod_key: mcleod_id}
        data = await self._request("POST", "v2", "organizations", body=body)
        return int(data["id"])

    # ---- deals ---------------------------------------------------------

    @staticmethod
    def _deal(d: dict) -> Deal:
        return Deal(
            id=int(d["id"]), title=d.get("title") or "", owner_id=d.get("owner_id"),
            org_id=d.get("org_id"), pipeline_id=d.get("pipeline_id"), status=d.get("status") or "",
        )

    async def open_reactivation_deal(self, p: Placement, org_id: int) -> Optional[Deal]:
        """The newest OPEN deal of this organization in REACTIVATION, or None."""
        data = await self._request(
            "GET", "v2", "deals",
            {"org_id": org_id, "pipeline_id": p.pipeline_id, "status": "open",
             "sort_by": "add_time", "sort_direction": "desc", "limit": 1},
        ) or []
        deals = [self._deal(d) for d in data if d.get("pipeline_id") == p.pipeline_id]
        return deals[0] if deals else None

    async def get_deal(self, deal_id: int) -> Optional[Deal]:
        try:
            data = await self._request("GET", "v2", f"deals/{deal_id}")
        except PipedriveError as e:
            if e.status == 404:
                return None
            raise
        return self._deal(data) if data else None

    async def create_deal(
        self, p: Placement, *, title: str, org_id: int, owner_id: int, mcleod_id: Optional[str],
    ) -> Deal:
        custom: dict[str, Any] = {p.deal_reactivation_key: p.deal_reactivation_option}
        if mcleod_id:
            custom[p.deal_mcleod_key] = mcleod_id
        data = await self._request("POST", "v2", "deals", body={
            "title": title, "org_id": org_id, "owner_id": owner_id,
            "pipeline_id": p.pipeline_id, "stage_id": p.stage_id, "custom_fields": custom,
        })
        return self._deal(data)

    async def set_owner(self, deal_id: int, owner_id: int) -> Deal:
        data = await self._request("PATCH", "v2", f"deals/{deal_id}", body={"owner_id": owner_id})
        return self._deal(data)


def _one(rows: list[dict], attr: str, wanted: str, what: str) -> dict:
    hits = [r for r in rows if (r.get(attr) or "").strip() == wanted]
    if len(hits) != 1:
        raise PipedriveConfigError(f"Pipedrive {what} {wanted!r}: {len(hits)} matches, need exactly 1")
    return hits[0]
