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
        return 1

    monkeypatch.setattr("app.push.send_to_account", fake_send)
    monkeypatch.setattr("app.routes_app.send_to_account", fake_send)
    monkeypatch.setattr("app.emails.send_email", lambda *a, **k: True)
    monkeypatch.setattr("app.activation.send_email", lambda *a, **k: True)
    monkeypatch.setattr("app.routes_app.send_email", lambda *a, **k: True)
    scheduled, reminders = [], []
    monkeypatch.setattr("app.followups.schedule", lambda call_id, delay: scheduled.append((call_id, delay)))
    monkeypatch.setattr("app.followups.schedule_emergency_reminder",
                        lambda call_id, delay: reminders.append((call_id, delay)))
    return {"push": sent, "scheduled": scheduled, "reminders": reminders}


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
