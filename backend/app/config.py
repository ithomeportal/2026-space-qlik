from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    QLIK_TENANT_URL: str = "https://mb01txe2h9rovgh.us.qlikcloud.com"
    QLIK_PRIVATE_KEY: str = ""
    QLIK_ISSUER: str = ""
    QLIK_KEY_ID: str = ""
    RESEND_API_KEY: str = ""
    TYPESENSE_API_KEY: str = ""
    TYPESENSE_HOST: str = "localhost"
    TYPESENSE_PORT: int = 8108
    TYPESENSE_PROTOCOL: str = "http"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    TIMEOFF_DATABASE_URL: str = ""
    SEED_SECRET: str = "change-me-in-production"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
