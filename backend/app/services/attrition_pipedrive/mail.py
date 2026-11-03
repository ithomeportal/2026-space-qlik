"""The two team notices — the requests' text VERBATIM.

90 days, reassigned (`space Attrition - Follow up.pdf`, page 5):
  Subject: (Deal Name) has been reassigned to (Sales Executive)
  Body:    Team, / The deal … has reached 90 days without any loads and has been
           reassigned to … / …, please meet with the KAM … / Thank you,

30 days, new deal (`Attrition follow up 30-89 days.pdf`, page 3, 2026-11-03):
  Subject: (Deal Name) | 30 days without loads – New PipeDrive deal created for
           account reactivation
  Body:    Team, / The deal … has reached 30 days without any loads moved. A new
           deal has been created … / (KAM's name), please follow up … / Thank you,
  One correction: the PDF's "with you progress" is sent as "with your progress".

(Deal Name) is the deal's title in Pipedrive at that moment — a hand-made deal
keeps its own title. Names are HTML-escaped.
"""
from __future__ import annotations

from html import escape

from app.services.team_perf_digest_html import FONT_STACK


def _paragraph_open() -> str:
    return f'<p style="margin:0 0 14px 0;font-family:{FONT_STACK};font-size:14px;color:#111827;">'


def subject_30_days(deal_name: str) -> str:
    return f"{deal_name} | 30 days without loads – New PipeDrive deal created for account reactivation"


def body_30_days(deal_name: str, kam_name: str) -> str:
    d, k, p = escape(deal_name), escape(kam_name), _paragraph_open()
    return (
        "<div>"
        f"{p}Team,</p>"
        f"{p}The deal <b>{d}</b> has reached 30 days without any loads moved. A new deal has been "
        "created in PipeDrive to track the account reactivation process.</p>"
        f"{p}{k}, please follow up with the customer and update the deal in PipeDrive "
        "with your progress.</p>"
        f"{p}Thank you,</p>"
        "</div>"
    )


def subject_for(deal_name: str, sales_name: str) -> str:
    return f"{deal_name} has been reassigned to {sales_name}"


def body_for(deal_name: str, sales_name: str) -> str:
    d, s, p = escape(deal_name), escape(sales_name), _paragraph_open()
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
