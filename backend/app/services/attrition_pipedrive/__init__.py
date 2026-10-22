"""Attrition → Pipedrive reactivation deals (request 2026-10-20, Iris / CEO).

Every day at 04:00 CST, against the Attrition WoW "Reactive" day count:

* 29–63 days without a load (the "5 to 9 Weeks" table) → a deal in the
  REACTIVATION pipeline, stage Re-OnHold, owned by the team's KAM — unless the
  organization already has an open REACTIVATION deal (108 hand-made ones exist).
* 90 days (a new crossing, 90–96) → that deal is reassigned to the team's Sales
  executive and the team is notified by e-mail.

Modules: ``config`` (routing, as data) · ``candidates`` (the SQL) ·
``pipedrive`` (the API) · ``mail`` (the notice) · ``runner`` (plan + execute).
"""
