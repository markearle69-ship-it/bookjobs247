import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_db}",
    "SECRET_KEY": "test-secret",
    "ADMIN_PASSWORD": "admin-pw",
    "PUBLIC_BASE_URL": "https://bj.example.com",
    "BRAND_URL": "https://stressfreeservicetools.com",
    "RETELL_API_KEY": "retell-key",
    "RETELL_AGENT_ID_US_FEMALE": "agent_us_f",
    "RETELL_AGENT_ID_US_MALE": "agent_us_m",
    "RETELL_AGENT_ID_GB_FEMALE": "agent_gb_f",
    "TWILIO_AUTH_TOKEN": "twilio-token",
    "TWILIO_VALIDATE_SIGNATURES": "false",
    "STRIPE_SECRET_KEY": "sk_test_x",
    "STRIPE_WEBHOOK_SECRET": "whsec_test",
    "STRIPE_PRICE_BASE_USD": "price_base_usd",
    "STRIPE_PRICE_USAGE_USD": "price_usage_usd",
    "STRIPE_PRICE_BASE_GBP": "price_base_gbp",
    "STRIPE_PRICE_USAGE_GBP": "price_usage_gbp",
})
