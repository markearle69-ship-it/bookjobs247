"""The On The Tools portfolio, as shown on the umbrella home page.

Add a tool here and it appears on the home page. "live" tools link to their
own page; "soon" tools show a "Tell me when it's ready" signup, so you can
gauge demand before building them. Signups are listed in /admin.
"""

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    status: str  # "live" | "soon"
    icon: str
    tagline: str
    blurb: str
    url: str = ""


def products() -> list[Product]:
    return [
        Product("calls", settings.app_name, "live", "📞",
                "Never miss a job because you were on one.",
                "An AI receptionist answers the calls you miss, takes the full job details and puts them on your phone.",
                url=f"/{settings.product_slug}"),
        Product("quotes", "Quotes", "soon", "🧾",
                "Professional quotes in two minutes, from your van.",
                "Describe the job, get a tidy, branded quote to send while you're still on site."),
        Product("followups", "Follow-ups", "soon", "🔁",
                "Chase every quote without lifting a finger.",
                "Polite, automatic follow-ups on quotes and enquiries, so jobs don't go cold."),
        Product("reviews", "Reviews", "soon", "⭐",
                "More 5-star reviews, on autopilot.",
                "Ask happy customers for a Google review at the right moment, without the awkward ask."),
    ]


def product(key: str) -> Product | None:
    return next((p for p in products() if p.key == key), None)
