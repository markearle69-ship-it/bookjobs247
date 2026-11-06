import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Account
from app.security import SESSION_COOKIE, hash_password, make_session


@pytest.fixture(autouse=True)
def fresh_db():
    from app.trades import seed_trades
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as s:
        seed_trades(s)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    return TestClient(app, base_url="https://bj.example.com")


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """No real push/email/followup timers in tests."""
    sent = []
    def fake_send(db, a, t, b, url="/app", urgent=False):
        sent.append((a.id, t, b, urgent))
        return 1 if a.push_subscriptions else 0

    monkeypatch.setattr("app.push.send_to_account", fake_send)
    monkeypatch.setattr("app.routes_app.send_to_account", fake_send)
    emails = []

    def fake_email(to, subject, body):
        emails.append((to, subject, body))
        return True

    for mod in ("app.emails", "app.activation", "app.routes_app", "app.push", "app.followups",
                "app.routes_webhooks"):
        monkeypatch.setattr(f"{mod}.send_email", fake_email)
    return {"push": sent, "emails": emails}


def make_account(db, **kw):
    defaults = dict(email="joe@example.com", password_hash=hash_password("password1"), business_name="Joe's Plumbing",
                    owner_name="Joe", trade="Plumber", trade_key="plumber", owner_phone="+15550001111", country="US",
                    onboarding_complete=True, subscription_status="active", twilio_number="+15557654321",
                    stripe_customer_id="cus_1")
    defaults.update(kw)
    a = Account(**defaults)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def login(client, account):
    client.cookies.set(SESSION_COOKIE, make_session(account.id))
