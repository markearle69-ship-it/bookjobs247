"""The trade library: what the assistant should ask for each kind of business,
what counts as an emergency, and the marketing copy for /for/<slug> pages.

The questions/emergency text are copied into the database on first start
(see seed_trades) and can then be edited in /admin/trades without a deploy.
The marketing copy stays here.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class TradeDefault:
    key: str
    label: str
    group: str
    questions: str
    emergency: str
    # Marketing page (/for/<slug>)
    slug: str = ""
    plural: str = ""
    example_caller: str = ""
    example_job: str = ""
    keywords: tuple = field(default_factory=tuple)


GROUPS = ["Plumbing & heating", "Electrical & HVAC", "Building & roofing", "Emergency & home services"]

DEFAULTS: list[TradeDefault] = [
    # ---------------- Plumbing & heating
    TradeDefault(
        "plumber", "Plumber", "Plumbing & heating",
        questions="- What's the problem: leak, blockage, no water, burst pipe, toilet, tap, or new installation?\n"
                  "- Where in the property is it (kitchen, bathroom, outside)?\n"
                  "- If it's a leak: is water still coming out, and have they been able to turn the water off at the "
                  "stopcock / main shut-off valve?\n"
                  "- Is it a house, flat/apartment or business premises?",
        emergency="Water actively leaking or flooding, a burst pipe, no water at all, or a sewage backup. If water "
                  "is near electrics, tell them to keep away and turn off the electricity at the fuse box only if it "
                  "is safe to do so.",
        slug="plumbers", plural="plumbers",
        example_caller="Hi, I've got water pouring through my kitchen ceiling, can someone come out today?",
        example_job="Burst pipe, water coming through kitchen ceiling. Stopcock off. Wants someone today."),
    TradeDefault(
        "heating", "Heating engineer / boiler", "Plumbing & heating",
        questions="- Is it a breakdown, a service, or a new boiler / system?\n"
                  "- Do they have heating, hot water, both, or neither?\n"
                  "- The make of the boiler or system if they know it, and any error code showing.\n"
                  "- Anyone vulnerable in the property (elderly, young children, unwell)?",
        emergency="No heating or hot water in cold weather, especially with vulnerable people in the property, or "
                  "water leaking from the boiler. If they can smell gas, stop and tell them to leave the property, "
                  "not use switches, and call {{gas_emergency}} straight away.",
        slug="heating-engineers", plural="heating engineers",
        example_caller="My boiler's showing an F28 error and we've got no heating, and I've got a newborn at home.",
        example_job="Boiler breakdown, F28 error, no heating. Newborn in the property."),
    TradeDefault(
        "gas", "Gas engineer", "Plumbing & heating",
        questions="- What appliance is it: boiler, cooker/hob, fire, or a safety certificate / inspection?\n"
                  "- Is it a breakdown, installation, service or certificate (e.g. landlord certificate)?\n"
                  "- If a certificate: how many appliances, and when is it due?",
        emergency="Any smell of gas, or carbon monoxide alarm going off: tell them to get everyone out, not use "
                  "electrical switches or flames, and call {{gas_emergency}} right now, before anything else.",
        slug="gas-engineers", plural="gas engineers",
        example_caller="I need a landlord gas safety certificate for a flat, it runs out at the end of the month.",
        example_job="Landlord gas safety certificate, 1 flat, due end of month."),
    TradeDefault(
        "drainage", "Drainage", "Plumbing & heating",
        questions="- What's blocked: sink, toilet, shower, outside drain or main sewer?\n"
                  "- Is it overflowing or backing up into the property?\n"
                  "- Is it just their property, or are neighbours affected too?",
        emergency="Sewage backing up into the property or a drain overflowing.",
        slug="drainage", plural="drainage engineers",
        example_caller="The drain outside is overflowing and it's starting to come up the toilet.",
        example_job="Outside drain overflowing, backing up into downstairs toilet."),
    # ---------------- Electrical & HVAC
    TradeDefault(
        "electrician", "Electrician", "Electrical & HVAC",
        questions="- What's the job: no power, tripping fuse box / breaker, faulty socket or light, new installation, "
                  "rewire, EV charger, or safety certificate / inspection?\n"
                  "- Is the whole property affected or just part of it?\n"
                  "- Is it a house, flat/apartment or business premises?",
        emergency="No power to the whole property, burning smells, sparking, smoke, scorch marks or exposed wiring. "
                  "Tell them not to touch it and, if safe, to switch off at the main switch. If there is fire or "
                  "smoke, call {{emergency_number}} first.",
        slug="electricians", plural="electricians",
        example_caller="Half the sockets in my house have stopped working and the breaker keeps tripping.",
        example_job="Breaker keeps tripping, half the sockets dead."),
    TradeDefault(
        "hvac", "HVAC / air conditioning", "Electrical & HVAC",
        questions="- Is it heating, air conditioning or both?\n"
                  "- Is it not working at all, working poorly, making noise, or leaking?\n"
                  "- Is it a repair, a service/tune-up, or a new install / replacement?\n"
                  "- The make or age of the system if they know it.",
        emergency="No cooling in extreme heat or no heating in freezing weather, especially with elderly people, "
                  "babies or unwell people in the property.",
        slug="hvac", plural="HVAC companies",
        example_caller="Our AC stopped blowing cold air and it's 100 degrees, my mom lives with us.",
        example_job="AC not cooling, elderly resident, very hot day."),
    TradeDefault(
        "solar", "Solar / renewables", "Electrical & HVAC",
        questions="- Is it a new installation quote, or a problem with an existing system?\n"
                  "- If new: roughly how big is the roof and is it a house or business?\n"
                  "- If existing: what's happening (no generation, inverter error, battery issue)?",
        emergency="Burning smell, smoke or sparking from panels, inverter or battery: tell them to keep away and "
                  "call {{emergency_number}} if there's fire or smoke.",
        slug="solar-installers", plural="solar installers",
        example_caller="I'd like a quote for solar panels and a battery on my house.",
        example_job="Quote: solar panels plus battery, house."),
    # ---------------- Building & roofing
    TradeDefault(
        "builder", "Builder", "Building & roofing",
        questions="- What's the project: extension, renovation, repair, wall, groundwork or something else?\n"
                  "- Roughly how big is it, and is there a design or plans already?\n"
                  "- When are they hoping to start?",
        emergency="Structural damage that makes the property unsafe, such as a collapsed wall or ceiling.",
        slug="builders", plural="builders",
        example_caller="We want a quote for a single-storey kitchen extension, we've got the plans approved.",
        example_job="Single-storey kitchen extension quote, plans approved."),
    TradeDefault(
        "roofer", "Roofer", "Building & roofing",
        questions="- Is it a leak, storm damage, missing tiles/shingles, gutters, or a new roof?\n"
                  "- If a leak: is water coming in right now, and where?\n"
                  "- What type of property and roughly how many storeys?",
        emergency="Water actively coming in through the roof, or storm damage leaving the roof open.",
        slug="roofers", plural="roofers",
        example_caller="The storm last night took some tiles off and water's coming into the bedroom.",
        example_job="Storm damage, missing tiles, water coming into bedroom."),
    TradeDefault(
        "carpenter", "Carpenter / joiner", "Building & roofing",
        questions="- What's the job: doors, windows, kitchen fitting, stairs, flooring, fitted furniture, decking?\n"
                  "- Is it a repair or new work, and roughly how much?\n"
                  "- Any timescale they're working to?",
        emergency="An external door or window that won't close or lock, leaving the property insecure.",
        slug="carpenters", plural="carpenters and joiners",
        example_caller="I need three internal doors hung and some skirting boards replaced.",
        example_job="Hang 3 internal doors, replace skirting."),
    TradeDefault(
        "painter", "Painter & decorator", "Building & roofing",
        questions="- Interior, exterior or both?\n"
                  "- How many rooms, or roughly how big is the area?\n"
                  "- Any wallpapering, plastering repairs or woodwork included?\n"
                  "- When would they like it done?",
        emergency="Rarely urgent. Treat as flexible unless they say otherwise.",
        slug="painters-decorators", plural="painters and decorators",
        example_caller="Can you give me a price to paint the outside of a three-bed semi?",
        example_job="Exterior paint, 3-bed semi-detached house."),
    TradeDefault(
        "handyman", "Handyman", "Building & roofing",
        questions="- What jobs do they need doing? Get a short list if there are several.\n"
                  "- Do they have the materials or parts already?\n"
                  "- Roughly how long they think it will take.",
        emergency="Rarely urgent. Treat as flexible unless something is unsafe or insecure.",
        slug="handymen", plural="handymen",
        example_caller="I've got a few jobs, a shelf, a dripping tap and a gate that won't shut.",
        example_job="Odd jobs: put up shelf, dripping tap, fix gate latch."),
    TradeDefault(
        "landscaper", "Landscaper / gardener", "Building & roofing",
        questions="- Is it regular maintenance, a one-off tidy-up, or a landscaping project (patio, fencing, turf, "
                  "decking)?\n"
                  "- Roughly how big is the garden or area?\n"
                  "- Any access issues (no side access, steps)?",
        emergency="A fallen tree or fence that is blocking access or dangerous.",
        slug="landscapers", plural="landscapers and gardeners",
        example_caller="We need a new fence along the back, about 20 metres, the old one blew down.",
        example_job="Replace ~20m fence at back of garden, blew down."),
    # ---------------- Emergency & home services
    TradeDefault(
        "locksmith", "Locksmith", "Emergency & home services",
        questions="- Are they locked out right now, or is it a lock change, repair or upgrade?\n"
                  "- If locked out: is anyone vulnerable left inside (child, pet, someone unwell)? Is it a house, "
                  "car or business?\n"
                  "- What kind of door or lock if they know (uPVC, wooden, multipoint, deadbolt)?",
        emergency="Locked out right now, a child or vulnerable person locked inside (tell them to call "
                  "{{emergency_number}} if anyone is in danger), or the property can't be secured after a break-in.",
        slug="locksmiths", plural="locksmiths",
        example_caller="I've locked myself out and my toddler's inside asleep.",
        example_job="Locked out, toddler inside. Needs entry ASAP."),
    TradeDefault(
        "pest_control", "Pest control", "Emergency & home services",
        questions="- What pest: mice/rats, wasps/bees, bed bugs, cockroaches, ants, birds or something else?\n"
                  "- Where are they seeing it, and for how long?\n"
                  "- Is it a home or a business (food businesses may need it urgently)?",
        emergency="A wasp or bee nest near a doorway or where someone is allergic, or pests in a food business.",
        slug="pest-control", plural="pest control companies",
        example_caller="There's a wasp nest right above our front door and my son's allergic.",
        example_job="Wasp nest above front door, child allergic."),
    TradeDefault(
        "cleaner", "Cleaning", "Emergency & home services",
        questions="- What kind of clean: regular, one-off deep clean, end of tenancy / move-out, office, carpets?\n"
                  "- How big is the property (bedrooms/bathrooms or rough size)?\n"
                  "- What day or date do they need it?",
        emergency="Rarely urgent. End-of-tenancy deadlines may be time-sensitive, so note the date.",
        slug="cleaners", plural="cleaning companies",
        example_caller="I need an end of tenancy clean for a two-bed flat this Friday.",
        example_job="End of tenancy clean, 2-bed flat, needed Friday."),
    TradeDefault(
        "garage_doors", "Garage doors", "Emergency & home services",
        questions="- Is the door stuck open, stuck shut, noisy, or is it a new door?\n"
                  "- Manual or electric/automatic? Any broken spring or cable?\n"
                  "- Is a car stuck inside?",
        emergency="Door stuck open leaving the property insecure, or a car trapped inside that they need. Tell "
                  "them not to try to lift a door with a broken spring.",
        slug="garage-doors", plural="garage door companies",
        example_caller="My garage door spring snapped and my car's stuck inside, I need it for work.",
        example_job="Broken spring, door stuck shut, car trapped inside."),
    TradeDefault(
        "appliance_repair", "Appliance repair", "Emergency & home services",
        questions="- Which appliance: washing machine, dryer, dishwasher, fridge/freezer, oven, other?\n"
                  "- The make, and model if they have it handy.\n"
                  "- What's it doing: not starting, leaking, error code, noise?",
        emergency="A leaking appliance flooding the floor, a fridge/freezer full of food that has stopped working, "
                  "or any burning smell (tell them to unplug it if safe).",
        slug="appliance-repair", plural="appliance repair engineers",
        example_caller="My freezer's stopped working and it's full of food.",
        example_job="Freezer stopped working, full of food."),
    TradeDefault(
        "removals", "Removals / moving", "Emergency & home services",
        questions="- Moving from where to where (towns or postcodes/ZIPs are fine)?\n"
                  "- How big is the move (number of bedrooms, or just a few items)?\n"
                  "- What date, and is it flexible?\n"
                  "- Do they need packing or storage?",
        emergency="Rarely urgent. Note the move date clearly.",
        slug="removals", plural="removal companies",
        example_caller="We're moving a three-bed house across town on the 14th, can you quote?",
        example_job="3-bed house move across town on the 14th."),
]

OTHER_QUESTIONS = ("- What the job is, with enough detail to understand it.\n"
                   "- Where it is, and roughly how big a job it is.\n"
                   "- When they'd like it done.")
OTHER_EMERGENCY = "Anything the caller says is urgent or unsafe."

BY_KEY = {t.key: t for t in DEFAULTS}
BY_SLUG = {t.slug: t for t in DEFAULTS if t.slug}


def seed_trades(db: Session) -> None:
    """Insert any default trade not yet in the database. Never overwrites
    your edits from /admin/trades."""
    from .models import TradeTemplate

    existing = {k for (k,) in db.query(TradeTemplate.key).all()}
    for i, t in enumerate(DEFAULTS):
        if t.key not in existing:
            db.add(TradeTemplate(key=t.key, label=t.label, group=t.group, questions=t.questions,
                                 emergency=t.emergency, sort_order=i * 10))
    db.commit()


def grouped_trades(db: Session) -> list[tuple[str, list]]:
    from .models import TradeTemplate

    rows = db.query(TradeTemplate).filter(TradeTemplate.active.is_(True)).order_by(TradeTemplate.sort_order).all()
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r.group or "Other trades", []).append(r)
    order = GROUPS + [g for g in groups if g not in GROUPS]
    return [(g, groups[g]) for g in order if g in groups]


def marketing_trades() -> list[TradeDefault]:
    return [t for t in DEFAULTS if t.slug]
