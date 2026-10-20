"""Customer load-status e-mails (PCA / Central Texas Corrugated, request 2026-10-20).

Four daily e-mails — DONNA, LAREDO, EL PASO, REYNOSA — each sent five times a
day at fixed CST hours with three sections: loads in progress, loads scheduled
to pick up (today or earlier, not picked up yet) and loads delivered in the
last 24 hours. Full spec: ``docs/SPEC-CUSTOMER-STATUS-EMAIL.md``.

Modules:
  config  — the four reports as data (lanes, subject, hours, recipients)
  data    — the datalake reads (one query per source, never per load)
  cards   — pure classification of a load into a bucket + display fields
  html    — Outlook-safe rendering, Magaly's Xink signature
  sender  — the scheduled slot run, the send-once log, test routing
"""
