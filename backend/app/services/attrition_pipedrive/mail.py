"""The 90-day reassignment notice — the request's text VERBATIM (PDF page 5).

Subject: (Deal Name) has been reassigned to (Sales Executive)
Body:    Team, / The deal … has reached 90 days without any loads and has been
         reassigned to … / …, please meet with the KAM … / Thank you,

(Deal Name) is the deal's title in Pipedrive as it stands when the job reassigns
it — a hand-made deal keeps its own title. Names are HTML-escaped.
"""
from __future__ import annotations

from html import escape

from app.services.team_perf_digest_html import FONT_STACK


def subject_for(deal_name: str, sales_name: str) -> str:
    return f"{deal_name} has been reassigned to {sales_name}"


def body_for(deal_name: str, sales_name: str) -> str:
    d, s = escape(deal_name), escape(sales_name)
    p = f'<p style="margin:0 0 14px 0;font-family:{FONT_STACK};font-size:14px;color:#111827;">'
    return (
        "<div>"
        f"{p}Team,</p>"
        f"{p}The deal <b>{d}</b> has reached 90 days without any loads and has been "
        f"reassigned to <b>{s}</b>.</p>"
        f"{p}{s}, please meet with the KAM to gather all relevant information before "
        "reaching out to the customer.</p>"
        f"{p}Thank you,</p>"
        "</div>"
    )
