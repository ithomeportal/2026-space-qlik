"""XRay DFW GM tab — merge orders that share a PO (Bruno PDF 2026-11-02, GM R1).

The request, verbatim: *"If two identical PO values exist, display only the
records where the BOL column matches the first 8 digits of the PO column.
However, calculate $ Revenue / $ Profit as the sum of both orders, Margin % =
Profit / Revenue. Add an icon to identify orders where two identical PO values
exist."*

What the data looks like (live gold, GM C/O CTSI, TEAM-DFW, 2026, measured
2026-11-02): 1,281 POs starting with 8 digits carry 2+ orders — a revenue leg
plus a $0 return leg whose carrier pay is a pure loss (e.g. 0350189 $3,714 /
$2,014 and 0350156 $0 / −$1,700 under PO ``55374191 / 55375236``).

The decisions this module encodes — each one is a case the PDF did not cover:

* **Numeric POs only** — ``po ~ '^[0-9]{8}'``. "The first 8 digits" presumes
  one; free-text POs (``CISCO: 19054`` ×11 orders over 2 months, ``TONU``,
  ``L246``, ``ACA…``) are recurring labels, not round-trip pairs, and are left
  alone.
* **BOL compared on its first 8 characters**, not whole. McLeod users annotate
  the BOL (``53167922*not on aim report``); a whole-value compare left 3 groups
  with NO match. With the prefix compare every numeric group has ≥1 match.
* **Tie-break** (18 groups where both orders carry the same BOL): the
  revenue-bearing order, then the earliest departure, then the lowest order id
  — so the kept row is the leg that was actually billed.
* **3+ orders on one PO** (2 groups) merge the same way: every member sums in.
* **Grouped per customer** — the partition is ``(customer, po)``, so the flag
  can never merge two shippers that happen to reuse a PO string.
* 🔴 **Anchored on the kept order's departure** (decision 2026-11-02). 48 pairs
  straddle a month (max gap 12.1 days). The merged row lives entirely in the
  window of its KEPT order; a partner outside the window still sums in, and a
  window holding only the partner shows nothing for that PO. Partners are
  searched ``PARTNER_DAYS`` either side of the window, and a PO whose orders
  spread wider than ``PARTNER_DAYS`` is treated as a REUSED number and left
  unmerged — so a group never depends on how long the range is. ⚠ So the GM tab's
  Totals for a month can differ from Contract vs Spot's by the boundary legs —
  that is the requested definition, not drift.

Every other filter (sub-team, lane, contract type, equipment, charge) applies
to the MEMBERS before grouping, exactly as it applies to unmerged rows.
"""

from __future__ import annotations

# Measured max gap inside a numeric-PO group: 12.1 days (2026, 1,281 groups).
# 31 leaves 2.5× headroom at ~400 extra GM orders per side — negligible.
PARTNER_DAYS = 31

# ORDER BY over the merged rows, keyed exactly like `_ALL_ORDERS_SORT`.
# Revenue/profit sort on the COMBINED values the row displays. Every fragment
# ends in (id, company_id), unique in v4, so LIMIT/OFFSET paging is total.
MERGED_SORT: dict[str, str] = {
    "departure_desc": "r.departure DESC NULLS LAST, r.id DESC, r.company_id DESC",
    "departure_asc": "r.departure ASC NULLS LAST, r.id DESC, r.company_id DESC",
    "order_desc": "r.id DESC, r.po DESC NULLS LAST, r.company_id DESC",
    "order_asc": "r.id ASC, r.po DESC NULLS LAST, r.company_id DESC",
    "revenue_desc": "r.grp_revenue DESC NULLS LAST, r.id DESC, r.company_id DESC",
    "revenue_asc": "r.grp_revenue ASC NULLS LAST, r.id DESC, r.company_id DESC",
    "profit_desc": "r.grp_profit DESC NULLS LAST, r.id DESC, r.company_id DESC",
    "profit_asc": "r.grp_profit ASC NULLS LAST, r.id DESC, r.company_id DESC",
}


def merged_cte(
    *, where: str, p_start: int, p_end: int, charge_filter: str,
    sub_team_expr: str, entity_expr: str,
) -> str:
    """``WITH base …, keyed …, r …`` — one row per order in the widened
    window, each carrying its group's totals and its rank inside the group.

    The caller adds ``WHERE r.rn = 1 AND <r.departure in window>``.
    """
    return f"""
        WITH base AS (
          SELECT
            {sub_team_expr} AS team,
            br4.id,
            -- RAW (padded 'TMS '): the movement LATERAL joins on it.
            br4.company_id,
            {entity_expr} AS customer,
            TRIM(br4.origin_name) AS origin,
            TRIM(br4.dest_name)   AS destination,
            br4.origin_actual_departure AS departure,
            br4.total_charge,
            br4.margin_amt,
            COALESCE(TRIM(br4.contract_type_descr), '')   AS contract_type,
            COALESCE(TRIM(br4.equipment_group_descr), '') AS equipment_group,
            NULLIF(TRIM(COALESCE(cv.blnum, '')), '') AS bol,
            NULLIF(TRIM(COALESCE(cv.po, '')), '')    AS po
          FROM public.mcleod_gld_budget_report_v4 br4
          -- (id, company_id) is customer_view's PRIMARY KEY: cannot fan out.
          LEFT JOIN public.mcleod_gld_customer_view cv
                 ON cv.id = br4.id AND cv.company_id = br4.company_id
          WHERE {where}
            AND br4.origin_actual_departure >= (${p_start}::date - {PARTNER_DAYS})
            AND br4.origin_actual_departure <  (${p_end}::date + {PARTNER_DAYS + 1})
            {charge_filter}
        ),
        cand AS (
          SELECT b.*,
                 -- Only an 8-digit PO groups; anything else is its own group.
                 CASE WHEN b.po ~ '^[0-9]{{8}}' THEN b.po END AS cand_po,
                 (b.po ~ '^[0-9]{{8}}' AND LEFT(b.bol, 8) = LEFT(b.po, 8)) AS bol_match
          FROM base b
        ),
        keyed AS (
          SELECT c.*,
                 -- ⚠ A PO whose orders spread wider than PARTNER_DAYS is a
                 -- REUSED number, not a round trip: left unmerged. Without this
                 -- the group would depend on the range — YTD would merge a Feb
                 -- and a Sep order that two monthly views keep apart.
                 CASE WHEN c.cand_po IS NOT NULL
                       AND MAX(c.departure) OVER pc - MIN(c.departure) OVER pc
                           <= INTERVAL '{PARTNER_DAYS} days'
                      THEN c.cand_po END AS grp_po
          FROM cand c
          WINDOW pc AS (PARTITION BY c.customer, c.cand_po)
        ),
        r AS (
          SELECT k.*,
                 COUNT(*)                         OVER g AS grp_n,
                 COALESCE(SUM(k.total_charge) OVER g, 0) AS grp_revenue,
                 COALESCE(SUM(k.margin_amt)   OVER g, 0) AS grp_profit,
                 jsonb_agg(jsonb_build_object(
                     'id', TRIM(k.id), 'bol', k.bol,
                     'departure', k.departure,
                     'revenue', k.total_charge, 'profit', k.margin_amt
                 )) OVER g AS grp_members,
                 ROW_NUMBER() OVER (
                     PARTITION BY k.customer, COALESCE(k.grp_po, k.id || '|' || k.company_id)
                     ORDER BY k.bol_match DESC NULLS LAST,
                              (COALESCE(k.total_charge, 0) <> 0) DESC,
                              k.departure ASC NULLS LAST,
                              k.id ASC, k.company_id ASC
                 ) AS rn
          FROM keyed k
          WINDOW g AS (PARTITION BY k.customer, COALESCE(k.grp_po, k.id || '|' || k.company_id))
        )
    """


def kept_in_window(p_start: int, p_end: int) -> str:
    """The kept order of each group, by ITS departure (anchor rule)."""
    return (
        f"r.rn = 1 AND r.departure >= ${p_start}"
        f" AND r.departure < (${p_end}::date + 1)"
    )
