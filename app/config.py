from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Display names only - change via env vars, no rebuild needed.
    brand_name: str = "StressFree Service"
    app_name: str = "Call Capturer"
    # The umbrella site's URL. Requests arriving on that domain get the
    # umbrella home page at "/"; everything else (the app, signup, trade pages)
    # lives on PUBLIC_BASE_URL (callcapturer.com). One deployment serves both.
    brand_url: str = ""
    # Your Skool community, linked from the tools page footer. Blank hides it.
    community_url: str = "https://stressfreeservicesquad.com"
    community_name: str = "StressFree Service Squad"
    support_email: str = ""

    # This service's public HTTPS URL, no trailing slash. Used to build every
    # webhook URL (Twilio, Retell, Stripe redirects) and to validate Twilio
    # request signatures, which are computed over the exact public URL.
    public_base_url: str = "http://localhost:8000"

    database_url: str = "sqlite:///./callcapturer.db"

    # Signs login sessions and password-reset links. Empty = refuse to start
    # (see main.py) rather than silently signing with a guessable key.
    secret_key: str = ""
    # Password for /admin (you, the operator).
    admin_password: str = ""
    # Where operator alerts go (e.g. "UK number pool is empty").
    admin_email: str = ""

    # --- Retell ---
    retell_api_key: str = ""
    # Four shared agents: country (accent) x voice gender. Each call passes the
    # business's own details and trade script in as dynamic variables, so no
    # per-customer agent is ever created. Create them with scripts/setup_retell.py.
    retell_agent_id_us_female: str = ""
    retell_agent_id_us_male: str = ""
    retell_agent_id_gb_female: str = ""
    retell_agent_id_gb_male: str = ""

    # --- Twilio ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    # Turn off only for local testing - production must validate signatures.
    twilio_validate_signatures: bool = True

    # --- Stripe ---
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_meter_event_name: str = "agent_minutes"
    # Created by scripts/setup_stripe.py.
    stripe_price_base_usd: str = ""
    stripe_price_usage_usd: str = ""
    stripe_price_base_gbp: str = ""
    stripe_price_usage_gbp: str = ""

    # --- Web push (PWA notifications). Generate with scripts/generate_vapid_keys.py ---
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # --- Email (password resets, welcome, operator alerts) ---
    postmark_api_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def url(self, path: str) -> str:
        return self.public_base_url.rstrip("/") + path

    @property
    def brand_host(self) -> str:
        from urllib.parse import urlparse
        host = urlparse(self.brand_url).hostname or ""
        return host.removeprefix("www.")


settings = Settings()
