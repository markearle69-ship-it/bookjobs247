"""Create the Stripe meter, product and prices (USD + GBP) from app/plans.py.

    STRIPE_SECRET_KEY=sk_test_... python scripts/setup_stripe.py

Run once in test mode and once in live mode; prints the env vars to set.
Each price = flat monthly fee + metered usage price with graduated tiers
(first N minutes free, then the overage rate per minute).
"""

import sys
from pathlib import Path

import stripe

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.plans import PLANS  # noqa: E402


def main():
    if not settings.stripe_secret_key:
        sys.exit("STRIPE_SECRET_KEY is not set")
    stripe.api_key = settings.stripe_secret_key
    event_name = settings.stripe_meter_event_name

    meter = next((m for m in stripe.billing.Meter.list(limit=100).auto_paging_iter()
                  if m.event_name == event_name and m.status == "active"), None)
    if meter is None:
        meter = stripe.billing.Meter.create(
            display_name="Answered call minutes",
            event_name=event_name,
            default_aggregation={"formula": "sum"},
            customer_mapping={"type": "by_id", "event_payload_key": "stripe_customer_id"},
            value_settings={"event_payload_key": "value"},
        )
    print(f"Meter: {meter.id} ({event_name})")

    product = stripe.Product.create(name="BookJobs247 AI receptionist",
                                    description="AI call answering for missed calls")
    out = {}
    for country, plan in PLANS.items():
        suffix = plan.currency.upper()
        base = stripe.Price.create(
            product=product.id, currency=plan.currency, unit_amount=plan.monthly * 100,
            recurring={"interval": "month", "usage_type": "licensed"},
            nickname=f"Monthly {suffix}",
        )
        usage = stripe.Price.create(
            product=product.id, currency=plan.currency,
            recurring={"interval": "month", "usage_type": "metered", "meter": meter.id},
            billing_scheme="tiered", tiers_mode="graduated",
            tiers=[{"up_to": plan.included_minutes, "unit_amount": 0},
                   {"up_to": "inf", "unit_amount": plan.overage_minor}],
            nickname=f"Minutes {suffix} ({plan.included_minutes} included)",
        )
        out[f"STRIPE_PRICE_BASE_{suffix}"] = base.id
        out[f"STRIPE_PRICE_USAGE_{suffix}"] = usage.id

    print("\nAdd these to your environment:\n")
    for k, v in out.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
