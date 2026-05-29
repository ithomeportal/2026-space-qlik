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
    # UNLK-Financial DB (read-only) — exchange_rates table (Banxico FIX = DOF).
    # Optional: used only to PREFILL a suggested FX on Bonus Calculator; the
    # HR board-pinned rate is authoritative. Percent-encode $ -> %24 in the URL.
    FINANCIAL_DATABASE_URL: str = ""
    RESEND_API_KEY: str = ""
    TYPESENSE_API_KEY: str = ""
    TYPESENSE_HOST: str = "localhost"
    TYPESENSE_PORT: int = 8108
    TYPESENSE_PROTOCOL: str = "http"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    TIMEOFF_DATABASE_URL: str = ""
    SEED_SECRET: str = "change-me-in-production"

    # Microsoft Graph (admin-ms-api app) — used to send the RFP Performance
    # daily digest from ithome@unilinktransportation.com via /sendMail.
    # Requires Mail.Send Application permission with admin consent.
    MS_TENANT_ID: str = ""
    MS_CLIENT_ID: str = ""
    MS_CLIENT_SECRET: str = ""
    MS_SEND_FROM: str = "ithome@unilinktransportation.com"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
