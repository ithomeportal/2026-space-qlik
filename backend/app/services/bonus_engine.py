"""Bonus Calculator engine — framework-free port of Bruno's HR-Headquarters module.

Source of truth: ``bonus-calculator-mcleod-package/python/bonus_calculator.py``
(provided by Bruno, 2026-05-24). Ported here verbatim in spirit so the package's
Vitest/pytest expectations remain valid regression checks. The portal feeds this
engine with **live datalake** team metrics (see ``routers/bonus_calculator.py``)
instead of a sample workbook.

Rules (do NOT simplify without HR sign-off — see docs/SPEC-BONUS-CALCULATOR.md §7):
- KAM: weekly loads >= 100 -> load bracket; payout = loads * bracket% * $2.00
- Freight Match: margin bracket pays ONLY when weekly loads > 100; else $0 (unless wildcard)
- Tracking & Tracing: MONTHLY service avg -> service bracket; payout = loads * bracket% *
  $1.60, gated by the 100-load weekly minimum. (R8, Bruno 2026-06-03: the per-week
  service calculation from R4-R7 is REMOVED — every week shows and pays on the one
  calendar-month On time P&D, the same number as the team header SERVICE KPI.)
- Wildcard: team profit > $100,000 AND the SAME monthly service avg >= 95%;
  pays max(regular, wildcard). (R8 bug fix: eligibility previously read the
  weeks-union period average, which could clear 95% while the displayed monthly
  SERVICE was below it — Team 1 May: 94.67% shown yet "Eligible".) NOTE: the
  $100k profit gate still reads the weekly-bucket sum (`total_profit`); whether
  it should move to calendar-month profit like the add-ons is OPEN — emailed
  Bruno 2026-06-08, awaiting reply (see SPEC §R9 PENDING block).
- Profit add-ons (per employee): >$130k +$500, >$150k +$500, >=$170k +$500
  (ladder == Bruno's $500/$1,000/$1,500). R9 (2026-06-08): keyed off the
  CALENDAR-MONTH profit (header PROFIT KPI / team["monthlyProfit"]), NOT the
  weekly-bucket sum — the Mon→Sun buckets miss the 1st-3rd so the bucket sum
  could sit below $170k while the header showed >=$170k.
- Team-1 KAM: monthly profit > $150,000 -> $14,400 MXN / DOF fx (gate still on
  the weekly-bucket sum — same OPEN question as the wildcard, pending Bruno)
- Afterhours (Night/Weekend): average of the 4 day-teams' weekly T&T bonus
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

BonusRole = Literal["kam", "freight_match", "tracking_tracing"]
DataSourceMode = Literal["sample_workbook", "mcleod_tms", "manual_import"]


LOAD_COUNT_BRACKETS = [
    {"threshold": 100, "bonusPct": 0.8},
    {"threshold": 112.5, "bonusPct": 0.9},
    {"threshold": 125, "bonusPct": 1.0},
    {"threshold": 137.5, "bonusPct": 1.1},
    {"threshold": 150, "bonusPct": 1.2},
]

MARGIN_BRACKETS = [
    {"threshold": 0.185, "bonusPct": 0.7},
    {"threshold": 0.2, "bonusPct": 1.0},
    {"threshold": 0.21, "bonusPct": 1.1},
    {"threshold": 0.22, "bonusPct": 1.2},
    {"threshold": 0.23, "bonusPct": 1.3},
]

SERVICE_BRACKETS = [
    {"threshold": 0.95, "bonusPct": 0.7},
    {"threshold": 0.96, "bonusPct": 0.8},
    {"threshold": 0.97, "bonusPct": 0.9},
    {"threshold": 0.98, "bonusPct": 1.0},
    {"threshold": 0.99, "bonusPct": 1.1},
]

PAY_PER_LOAD = {
    "kam": 2.0,
    "freight_match": 1.6,
    "tracking_tracing": 1.6,
}

MONTHLY_PROFIT_BRACKETS = [
    {"threshold": 130000, "label": "130 bracket", "payoutUsd": 500},
    {"threshold": 150000, "label": "150 bracket", "payoutUsd": 500},
    {"threshold": 170000, "label": "170 bracket", "payoutUsd": 500},
]

# Default night FX (kept separate from team FX per Bruno Q5). HR-editable via settings.
DEFAULT_NIGHT_FX_RATE = 16.89


def normalize_percent(value: float) -> float:
    """Accepts 95.5 or 0.955 and returns 0.955."""
    return value / 100 if value > 1 else value


def get_bracket_bonus(value: float, brackets: List[Dict[str, float]]) -> float:
    bonus = 0.0
    for bracket in brackets:
        if value >= bracket["threshold"]:
            bonus = float(bracket["bonusPct"])
    return bonus


def calculate_profit_bracket_bonuses(monthly_profit_usd: float) -> List[Dict[str, Any]]:
    results = []
    for bracket in MONTHLY_PROFIT_BRACKETS:
        threshold = float(bracket["threshold"])
        achieved = monthly_profit_usd >= threshold if threshold == 170000 else monthly_profit_usd > threshold
        results.append(
            {
                "threshold": threshold,
                "label": bracket["label"],
                "payoutUsd": float(bracket["payoutUsd"] if achieved else 0),
            }
        )
    return results


def get_wildcard_bracket_index(normalized_service_average: float) -> int:
    matched_index = -1
    for index, bracket in enumerate(SERVICE_BRACKETS):
        if normalized_service_average >= bracket["threshold"]:
            matched_index = index
    return matched_index


def calculate_wildcard_bonus(
    employee: Dict[str, Any], total_profit: float, normalized_service_average: float
) -> Dict[str, Any]:
    wildcard_index = get_wildcard_bracket_index(normalized_service_average)
    is_eligible = total_profit > 100000 and wildcard_index >= 0
    role = employee["role"]

    if not is_eligible:
        return {
            "wildcardWeeklyUsd": 0.0,
            "wildcardBonusUsd": 0.0,
            "wildcardServiceBracketPct": 0.0,
            "wildcardEquivalentLoads": 0.0,
            "wildcardEquivalentMarginPct": 0.0,
            "wildcardRoleBonusPct": 0.0,
            "wildcardBasePayUsd": PAY_PER_LOAD[role],
            "wildcardRuleLabel": None,
        }

    service_bracket = SERVICE_BRACKETS[wildcard_index]
    load_bracket = LOAD_COUNT_BRACKETS[wildcard_index] if wildcard_index < len(LOAD_COUNT_BRACKETS) else LOAD_COUNT_BRACKETS[0]
    margin_bracket = MARGIN_BRACKETS[wildcard_index] if wildcard_index < len(MARGIN_BRACKETS) else MARGIN_BRACKETS[0]

    if role == "kam":
        role_bonus_pct = float(load_bracket["bonusPct"])
    elif role == "freight_match":
        role_bonus_pct = float(margin_bracket["bonusPct"])
    else:
        role_bonus_pct = float(service_bracket["bonusPct"])

    base_pay = PAY_PER_LOAD[role]
    wildcard_weekly_usd = float(load_bracket["threshold"]) * role_bonus_pct * base_pay

    return {
        "wildcardWeeklyUsd": wildcard_weekly_usd,
        "wildcardBonusUsd": wildcard_weekly_usd,
        "wildcardServiceBracketPct": float(service_bracket["threshold"]),
        "wildcardEquivalentLoads": float(load_bracket["threshold"]),
        "wildcardEquivalentMarginPct": float(margin_bracket["threshold"]),
        "wildcardRoleBonusPct": role_bonus_pct,
        "wildcardBasePayUsd": base_pay,
        "wildcardRuleLabel": (
            f"Weekly wildcard: monthly profit > $100,000 and service at or above "
            f"{service_bracket['threshold'] * 100:.0f}%; service bracket maps each week to "
            f"{load_bracket['threshold']:.1f} loads / {margin_bracket['threshold'] * 100:.1f}% margin."
        ),
    }


def calculate_team1_kam_bonus(team: Dict[str, Any], employee: Dict[str, Any], total_profit: float) -> Dict[str, Any]:
    is_team1_kam = team.get("id") == "team-1" and employee.get("role") == "kam"
    if not is_team1_kam or total_profit <= 150000:
        manual_bonus = float(employee.get("kamBonusUsd", 0) or 0)
        return {
            "kamBonusUsd": manual_bonus,
            "kamBonusMxn": manual_bonus * float(team.get("fxRate", 1) or 1),
            "kamBonusFxRate": float(team.get("fxRate", 1) or 1),
            "kamBonusRuleLabel": "Manual KAM bonus" if manual_bonus else None,
        }

    kam_bonus_mxn = 14400.0
    fx_rate = max(float(team.get("fxRate", 1) or 1), 1)
    return {
        "kamBonusUsd": kam_bonus_mxn / fx_rate,
        "kamBonusMxn": kam_bonus_mxn,
        "kamBonusFxRate": fx_rate,
        "kamBonusRuleLabel": "Team 1 KAM: $14,400 MXN / DOF when monthly profit is greater than $150,000 USD",
    }


def calculate_team_bonus(team: Dict[str, Any]) -> Dict[str, Any]:
    # R8 (Bruno 2026-06-03): ONE service number per team — the calendar-month
    # On time P&D (`monthlyServicePct`, what the header SERVICE KPI shows).
    # It drives the weekly display rows, the T&T bracket AND the wildcard gate,
    # so "94.67% shown but wildcard Eligible" can't happen again. The old
    # weeks-union period average remains only as a fallback for callers that
    # don't pass monthlyServicePct (package regression fixtures).
    if team.get("monthlyServicePct") is not None:
        service_average_pct = float(team["monthlyServicePct"])
    else:
        service_average_pct = (float(team["pickupServicePct"]) + float(team["deliveryServicePct"])) / 2
    normalized_service = normalize_percent(service_average_pct)

    weekly_rules = []
    for week in team["weeks"]:
        revenue = float(week.get("revenue", 0) or 0)
        gross_profit = float(week.get("grossProfit", 0) or 0)
        margin_pct = (
            normalize_percent(float(week["marginPct"]))
            if week.get("marginPct") is not None
            else (0 if revenue == 0 else gross_profit / revenue)
        )
        loads = float(week["loads"])
        # The weekly minimum of 100 loads is the gate for EVERY role (Bruno, 2026-05-26):
        # below it no bonus applies that week, even if margin/service clear their bracket.
        meets_load_minimum = loads >= 100
        weekly_rules.append(
            {
                "label": week["label"],
                "loads": loads,
                "revenue": revenue,
                "grossProfit": gross_profit,
                "marginPct": margin_pct,
                "meetsLoadMinimum": meets_load_minimum,
                "loadBonusPct": get_bracket_bonus(loads, LOAD_COUNT_BRACKETS),
                "marginBonusPct": get_bracket_bonus(margin_pct, MARGIN_BRACKETS) if meets_load_minimum else 0.0,
                # Monthly service bracket, gated by the week's 100-load minimum —
                # the Tracking & Tracing payout driver again as of R8 (Bruno
                # 2026-06-03), which REMOVED the R4-R7 per-week service calc.
                "serviceBonusPct": get_bracket_bonus(normalized_service, SERVICE_BRACKETS) if meets_load_minimum else 0.0,
                # R8: every week displays the SAME calendar-month On time P&D —
                # Bruno's mock literally repeats 94.67% across Week 1-4. The wire
                # fields keep their per-week names so the frontend table shape is
                # untouched; only the value source changed (was each week's own avg).
                "serviceAveragePct": service_average_pct,
                # Green "Actual Bonus %" On time P&D row: monthly bracket, UNGATED
                # display (row != money convention from R7 stands — a sub-100-load
                # week shows the bracket % while the payout above gates to $0).
                "serviceBonusPctWeekly": get_bracket_bonus(normalized_service, SERVICE_BRACKETS),
            }
        )

    total_revenue = sum(float(week.get("revenue", 0) or 0) for week in team["weeks"])
    total_profit = sum(float(week.get("grossProfit", 0) or 0) for week in team["weeks"])
    # R9 (Bruno 2026-06-08): the 130/150/170 profit brackets key off the
    # calendar-month profit (the header PROFIT KPI), NOT the weekly-bucket sum.
    # The Mon→Sun weekly buckets miss the 1st-3rd of the month, so the bucket
    # sum can sit below $170k while the header shows ≥$170k (Team 1 live: header
    # $180,982 ≥ 170k but the 170 bracket silently paid $0). Bruno: the $170k
    # limit was exceeded, so all three $500 ladders must show. Fixtures without a
    # monthly figure fall back to the bucket sum (same fallback shape as
    # monthlyServicePct, R8). Wildcard still uses the bucket sum (R3/R8 locked).
    bracket_profit_basis = (
        float(team["monthlyProfit"]) if team.get("monthlyProfit") is not None else total_profit
    )
    profit_brackets = calculate_profit_bracket_bonuses(bracket_profit_basis)
    wildcard_index = get_wildcard_bracket_index(normalized_service)
    wildcard_eligible = total_profit > 100000 and wildcard_index >= 0

    employees = []
    for employee in team["employees"]:
        role = employee["role"]
        regular_weekly_usd = []
        for rule in weekly_rules:
            # All three roles are gated by the 100-load weekly minimum, carried
            # inside each bracket % (loadBonusPct is 0 under 100 by construction;
            # marginBonusPct and serviceBonusPct are zeroed explicitly).
            # R8 (Bruno 2026-06-03): Tracking & Tracing pays on the MONTHLY
            # service bracket (serviceBonusPct) — the per-week bracket from
            # R6/R7 is gone with the weekly service calc. The ungated monthly
            # bracket still shows in the green row (serviceBonusPctWeekly), so
            # row != money on sub-100-load weeks, same convention as R7.
            if role == "kam":
                multiplier = rule["loadBonusPct"]
            elif role == "freight_match":
                multiplier = rule["marginBonusPct"]
            else:
                multiplier = rule["serviceBonusPct"]
            regular_weekly_usd.append(multiplier * rule["loads"] * PAY_PER_LOAD[role])

        wildcard = calculate_wildcard_bonus(employee, total_profit, normalized_service)
        wildcard_weekly_usd = wildcard["wildcardBonusUsd"]
        weekly_usd = [max(value, wildcard_weekly_usd) if wildcard_eligible else value for value in regular_weekly_usd]
        bonus_usd = sum(weekly_usd)
        wildcard_bonus_usd = wildcard_weekly_usd * len(weekly_rules) if wildcard_eligible else 0
        wildcard_applied_usd = sum(
            max(0, weekly_usd[index] - regular_weekly_usd[index]) for index in range(len(weekly_usd))
        )
        kam_bonus = calculate_team1_kam_bonus(team, employee, total_profit)
        legacy_addons = sum(float(value) for value in employee.get("addOnsUsd", []) or [])
        profit_bracket_bonus_usd = sum(float(bracket["payoutUsd"]) for bracket in profit_brackets)
        add_on_bonus_usd = kam_bonus["kamBonusUsd"] + legacy_addons + profit_bracket_bonus_usd
        total_bonus_usd = bonus_usd + add_on_bonus_usd
        bonus_mxn = total_bonus_usd * float(team["fxRate"])

        employees.append(
            {
                **employee,
                "weeklyUsd": weekly_usd,
                "regularWeeklyUsd": regular_weekly_usd,
                "regularBonusUsd": sum(regular_weekly_usd),
                "bonusUsd": bonus_usd,
                "wildcardWeeklyUsd": wildcard_weekly_usd,
                "wildcardBonusUsd": wildcard_bonus_usd,
                "wildcardAppliedUsd": wildcard_applied_usd,
                "wildcardRoleBonusPct": wildcard["wildcardRoleBonusPct"],
                "wildcardBasePayUsd": wildcard["wildcardBasePayUsd"],
                "wildcardRuleLabel": wildcard["wildcardRuleLabel"],
                **kam_bonus,
                "profitBracketBonuses": profit_brackets,
                "profitBracketBonusUsd": profit_bracket_bonus_usd,
                "addOnBonusUsd": add_on_bonus_usd,
                "totalBonusUsd": total_bonus_usd,
                "bonusMxn": bonus_mxn,
                "totalCompMxn": float(employee.get("salaryMxn", 0) or 0) + bonus_mxn,
            }
        )

    return {
        **team,
        "serviceAveragePct": service_average_pct,
        "wildcardEligible": wildcard_eligible,
        "wildcardServiceBracketPct": SERVICE_BRACKETS[wildcard_index]["threshold"] if wildcard_eligible else 0,
        "wildcardEquivalentLoads": LOAD_COUNT_BRACKETS[wildcard_index]["threshold"] if wildcard_eligible else 0,
        "wildcardEquivalentMarginPct": MARGIN_BRACKETS[wildcard_index]["threshold"] if wildcard_eligible else 0,
        "totalLoads": sum(float(week.get("loads", 0) or 0) for week in team["weeks"]),
        "totalRevenue": total_revenue,
        "totalProfit": total_profit,
        "marginPct": 0 if total_revenue == 0 else total_profit / total_revenue,
        "teamBonusUsd": sum(float(employee["totalBonusUsd"]) for employee in employees),
        "profitBracketBonuses": profit_brackets,
        "weeklyRules": weekly_rules,
        "employees": employees,
    }


def build_bonus_report(
    month: str,
    source: str,
    mode: DataSourceMode,
    teams: List[Dict[str, Any]],
    night_shift_employees: List[Dict[str, Any]],
    night_fx_rate: float = DEFAULT_NIGHT_FX_RATE,
    last_sync_label: Optional[str] = None,
    status_label: Optional[str] = None,
) -> Dict[str, Any]:
    calculated_teams = [calculate_team_bonus(team) for team in teams]

    tracking_tracing_team_bonuses = []
    for team in calculated_teams:
        tracking_employee = next((e for e in team["employees"] if e["role"] == "tracking_tracing"), None)
        weekly_usd = tracking_employee["weeklyUsd"] if tracking_employee else [0 for _ in team["weeks"]]
        tracking_tracing_team_bonuses.append(
            {"teamName": team["name"], "weeklyUsd": weekly_usd, "bonusUsd": sum(weekly_usd)}
        )

    week_count = max([len(t["weeklyUsd"]) for t in tracking_tracing_team_bonuses] or [0])
    tracking_average_weekly = []
    for week_index in range(week_count):
        if tracking_tracing_team_bonuses:
            total = sum(
                t["weeklyUsd"][week_index] if week_index < len(t["weeklyUsd"]) else 0
                for t in tracking_tracing_team_bonuses
            )
            tracking_average_weekly.append(total / len(tracking_tracing_team_bonuses))
        else:
            tracking_average_weekly.append(0)

    tracking_average_bonus_usd = sum(tracking_average_weekly)
    night_employees = []
    for employee in night_shift_employees:
        bonus_usd = tracking_average_bonus_usd if employee.get("receivesBonus") else 0
        bonus_mxn = bonus_usd * night_fx_rate
        night_employees.append(
            {
                **employee,
                "bonusUsd": bonus_usd,
                "bonusMxn": bonus_mxn,
                "totalCompMxn": float(employee.get("salaryMxn", 0) or 0) + bonus_mxn,
            }
        )

    team_bonus_usd = sum(t["teamBonusUsd"] for t in calculated_teams)
    night_shift_bonus_usd = sum(e["bonusUsd"] for e in night_employees)
    total_profit = sum(t["totalProfit"] for t in calculated_teams)
    grand_bonus_usd = team_bonus_usd + night_shift_bonus_usd

    return {
        "month": month,
        "source": source,
        "dataSource": {
            "mode": mode,
            "status": status_label
            or ("Connected" if mode == "mcleod_tms" else "Manual import" if mode == "manual_import" else "Pending McLeod credentials"),
            "requiredFields": [
                "teamId",
                "teamName",
                "weekLabel",
                "loads",
                "revenue",
                "grossProfit",
                "marginPct",
                "pickupServicePct",
                "deliveryServicePct",
                "fxRate",
            ],
            "lastSyncLabel": last_sync_label or "Not connected yet",
        },
        "criteria": {
            "loadCountBrackets": LOAD_COUNT_BRACKETS,
            "marginBrackets": MARGIN_BRACKETS,
            "serviceBrackets": SERVICE_BRACKETS,
            "payPerLoad": PAY_PER_LOAD,
        },
        "teams": calculated_teams,
        "nightShift": {
            "fxRate": night_fx_rate,
            "dayTeamAverageBonusUsd": tracking_average_bonus_usd,
            "trackingTracingAverageBonusUsd": tracking_average_bonus_usd,
            "trackingTracingTeamBonuses": tracking_tracing_team_bonuses,
            "trackingTracingAverageWeeklyBonuses": tracking_average_weekly,
            "employees": night_employees,
            "totalBonusUsd": night_shift_bonus_usd,
        },
        "sales": [],
        "totals": {
            "teamBonusUsd": team_bonus_usd,
            "nightShiftBonusUsd": night_shift_bonus_usd,
            "salesBonusUsd": 0,
            "grandBonusUsd": grand_bonus_usd,
            "totalProfit": total_profit,
            "bonusAsPctOfProfit": 0 if total_profit == 0 else (grand_bonus_usd / total_profit) * 100,
        },
    }
