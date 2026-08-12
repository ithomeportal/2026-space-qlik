from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    # Aiven aivn_datalake_gold — source for code-made reports (e.g. eSavings from Carriers)
    SAVINGS_DATABASE_URL: str = ""
    # Aiven automations_db — source for n8n-produced tables
    # (e.g. contract_performance_analysis powering Track Award Loads)
    AUTOMATIONS_DATABASE_URL: str = ""
    # Aiven fresh_services_unlk — FreshService Tickets/Agents mirror
    # populated by an external Spark ETL. Powers the IT Tickets Mgmt report.
    FRESHSERVICE_DATABASE_URL: str = ""
    # Aiven unilink_portal_ap — the AP_module app's own DB (carriers +
    # fmcsa_sms_data). Read-only. Powers the Carrier SMS Score report.
    # Percent-encode $ -> %24 in the URL (Render strips $$).
    AP_DATABASE_URL: str = ""
    # Aiven modern_pricing_portal — the quoting portal's own DB. Read-only,
    # SELECT on spot_report_condensed ONLY (role spaceqlik_pricing_ro).
    # Source of the HD Spot funnel (offered/quoted/awarded).
    # Percent-encode $ -> %24 in the URL (Render strips $$).
    PRICING_DATABASE_URL: str = ""
    # UNLK-Financial DB (read-only) — exchange_rates table (Banxico FIX = DOF).
    # Optional: used only to PREFILL a suggested FX on Bonus Calculator; the
    # HR board-pinned rate is authoritative. Percent-encode $ -> %24 in the URL.
    FINANCIAL_DATABASE_URL: str = ""
    RESEND_API_KEY: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    TIMEOFF_DATABASE_URL: str = ""
    SEED_SECRET: str = "change-me-in-production"

    # Shared secret proving a request came from our Next.js proxy.
    #
    # `require_user` trusts the JSON identity in the Authorization header, since
    # the proxy has already validated the NextAuth session. But this backend is
    # directly reachable on the public internet, so without a secret ANY caller
    # could assert `roles:["admin"]` with a one-line curl and read every report.
    # The proxy sends this as `X-Proxy-Secret`; the backend compares it with
    # `hmac.compare_digest`.
    #
    # ⚠ Deliberately FAIL-OPEN when empty: enforcement switches on only once the
    # value is set on Render. That makes the rollout order safe (deploy code →
    # set Vercel → set Render) with no window where the frontend is sending a
    # header the backend rejects, or vice versa. `main.py` logs a loud warning at
    # startup while it is unset. MUST be identical to Vercel's PROXY_SHARED_SECRET.
    PROXY_SHARED_SECRET: str = ""

    # Machine bearer for external schedulers (n8n) that PULL a rendered report
    # digest — currently only
    # `GET /api/custom/ops-portal-overview/team-digest-email`.
    #
    # Deliberately NOT PROXY_SHARED_SECRET: that secret's entire meaning is
    # "this request came through our Vercel proxy, so the identity in the
    # Authorization header is trustworthy". Handing it to a third-party
    # scheduler would let that scheduler self-assert `roles:["admin"]` on every
    # endpoint in the app, silently voiding role_report_access everywhere.
    #
    # ⚠ FAILS CLOSED, unlike PROXY_SHARED_SECRET: while this is empty the
    # machine-bearer path is disabled entirely and the endpoint is reachable
    # only through the normal report-access gate. An unset secret must never
    # mean "everyone passes".
    REPORTS_CRON_SECRET: str = ""

    # Microsoft Graph (admin-ms-api app) — used to send the RFP Performance
    # daily digest from ithome@unilinktransportation.com via /sendMail.
    # Requires Mail.Send Application permission with admin consent.
    MS_TENANT_ID: str = ""
    MS_CLIENT_ID: str = ""
    MS_CLIENT_SECRET: str = ""
    MS_SEND_FROM: str = "ithome@unilinktransportation.com"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
