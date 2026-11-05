"""Display pricing per country. The amounts actually charged live in Stripe
(created by scripts/setup_stripe.py from these same numbers), so if you
change a price, re-run that script and update the env price IDs too."""

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class Plan:
    currency: str
    symbol: str
    monthly: int  # whole units, e.g. 19 = $19
    included_minutes: int
    overage_minor: int  # per-minute overage in cents/pence

    @property
    def monthly_label(self) -> str:
        return f"{self.symbol}{self.monthly}"

    @property
    def overage_label(self) -> str:
        return f"{self.symbol}{self.overage_minor / 100:.2f}"


PLANS = {
    "US": Plan(currency="usd", symbol="$", monthly=29, included_minutes=60, overage_minor=25),
    "GB": Plan(currency="gbp", symbol="£", monthly=25, included_minutes=60, overage_minor=20),
}


def plan_for(country: str) -> Plan:
    return PLANS.get(country, PLANS["US"])


def stripe_prices_for(country: str) -> tuple[str, str]:
    """(flat monthly price id, metered usage price id) for this country."""
    if country == "GB":
        return settings.stripe_price_base_gbp, settings.stripe_price_usage_gbp
    return settings.stripe_price_base_usd, settings.stripe_price_usage_usd
