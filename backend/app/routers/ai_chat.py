"""AI chat — POST /api/custom/ai-chat/ask (contract SPEC-CONTRACTS.md §3).

Optional ``"mode": "daily_brief"`` (contract §5) adds the daily-brief prompt block.

Called by the teams-chat-ai Teams bot with `X-Bot-Assertion` (or, unchanged, by
the portal proxy). Answers a question by letting Claude call three read-only
tools that execute IN-PROCESS as the asking user (`app.services.ai_chat_tools`),
so every number comes from a report the user can already open.

Errors: 401/403 auth (bot_identity), 422 validation, 429 throttle,
503 {"detail":"ai chat not configured"} without ANTHROPIC_API_KEY,
502 {"detail":"ai model call failed"} when the model call fails (detail logged).
Design + lessons: docs/SPEC-AI-CHAT.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.clock import cst_now
from app.config import settings
from app.routers.bot_identity import require_ai_chat_user
from app.routers.deps import get_pool
from app.services import ai_chat_agent
from app.services import ai_chat_daily_brief as daily_brief
from app.services.ai_chat_tools import ToolSession, open_inprocess_client

router = APIRouter(prefix="/custom/ai-chat", tags=["ai-chat"])
logger = logging.getLogger(__name__)

# Whole-answer budget. The bot gives up at 150 s; answering 504 first lets it
# print "timed out" instead of a dead connection. Up to 7 model calls + tools.
AI_CHAT_TIMEOUT_SECONDS = 120.0


# ⚠ Module-level models only — inside a factory they 500 /openapi.json.
class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class AskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=10)
    # Contract §5: the bot sends "daily_brief" for "How is the day looking?". Anything
    # else (other strings, wrong case, numbers) is a 422; null/absent = a normal question.
    mode: Literal["daily_brief"] | None = None


class ReportUsed(BaseModel):
    key: str
    title: str
    path: str


class AskResponse(BaseModel):
    answer: str
    data_as_of: str | None
    reports_used: list[ReportUsed]
    tools_used: list[str]
    generated_at: str
    # daily_brief only: the per-team scoreboard for the Teams card (null otherwise).
    brief: dict | None = None


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    user: dict = Depends(require_ai_chat_user),
) -> AskResponse:
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ai chat not configured")

    pool = get_pool(request)
    async with open_inprocess_client(request.app) as client:
        session = ToolSession(app=request.app, identity=user, pool=pool, client=client)
        try:
            answer = await asyncio.wait_for(
                ai_chat_agent.run_conversation(
                    message=body.message,
                    history=[h.model_dump() for h in body.history],
                    session=session,
                    mode=body.mode,
                ),
                timeout=AI_CHAT_TIMEOUT_SECONDS,
            )
        except ai_chat_agent.ModelCallError:
            raise HTTPException(status_code=502, detail="ai model call failed") from None
        except TimeoutError:
            logger.warning("ai-chat answer exceeded %ss (tools used: %s)",
                           AI_CHAT_TIMEOUT_SECONDS, session.tools_used)
            raise HTTPException(status_code=504, detail="ai chat timed out") from None

    return AskResponse(
        answer=answer,
        data_as_of=session.data_as_of(),
        reports_used=[ReportUsed(**r) for r in session.reports_used.values()],
        tools_used=list(session.tools_used),
        generated_at=cst_now().isoformat(),
        brief=daily_brief.scoreboard_of(session.brief) if session.brief else None,
    )
