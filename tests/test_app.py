from app.forwarding import codes_for
from app.models import Account, Call, PushSubscription
from app.phone import normalize, pretty
from tests.helpers import client, db, fresh_db, login, make_account, no_side_effects  # noqa: F401


def test_signup_onboarding_then_subscribe(client, db):
    r = client.post("/signup", data={"email": "New@Example.com", "password": "password1",
                                     "business_name": "Spark Electric", "country": "GB"}, follow_redirects=False)
    assert r.headers["location"] == "/app/onboarding"
    assert client.get("/app", follow_redirects=False).headers["location"] == "/app/onboarding"
    r = client.post("/app/onboarding", data={"business_name": "Spark Electric", "owner_name": "Dave",
                                             "trade_key": "electrician", "owner_phone": "07700 900123",
                                             "answer_as": "Spark", "assistant_name": "Amy", "voice_gender": "male"},
                    follow_redirects=False)
    assert r.headers["location"] == "/app/subscribe"
    account = db.query(Account).one()
    assert account.email == "new@example.com" and account.owner_phone == "+447700900123"
    assert (account.trade_key, account.trade, account.answer_as, account.assistant_name, account.voice_gender) == \
        ("electrician", "Electrician", "Spark", "Amy", "male")
    page = client.get("/app/subscribe")
    assert "£25" in page.text and "£0.20" in page.text and "60 answered minutes" in page.text


def test_us_onboarding_requires_area_code(client, db):
    client.post("/signup", data={"email": "a@b.com", "password": "password1", "business_name": "Cool Air",
                                 "country": "US"})
    data = {"owner_name": "Al", "trade_key": "hvac", "owner_phone": "5551234567"}
    r = client.post("/app/onboarding", data=data, follow_redirects=False)
    assert r.status_code == 200 and "area code" in r.text
    assert 'value="Al"' in r.text  # what they typed is kept
    r = client.post("/app/onboarding", data=data | {"area_code": "512"}, follow_redirects=False)
    assert r.headers["location"] == "/app/subscribe"
    assert db.query(Account).one().area_code == "512"


def test_other_trade_free_text(client, db):
    a = make_account(db)
    login(client, a)
    client.post("/app/settings", data={"business_name": "Joe's", "owner_name": "Joe", "owner_phone": "5551234567",
                                       "trade_key": "other", "trade_other": "Window cleaner"})
    db.refresh(a)
    assert (a.trade_key, a.trade) == ("other", "Window cleaner")


def test_trade_landing_pages(client, db):
    r = client.get("/for/plumbers")
    assert r.status_code == 200 and "For plumbers" in r.text and "stopcock" in r.text and "$29" in r.text
    assert "trade=plumber" in r.text
    assert "£25" in client.get("/for/plumbers", headers={"accept-language": "en-GB,en;q=0.9"}).text
    assert client.get("/for/nope").status_code == 404
    home = client.get("/")
    assert "$500+" in home.text and "/for/electricians" in home.text


def test_signup_from_trade_page_preselects_trade(client, db):
    client.post("/signup", data={"email": "l@k.com", "password": "password1", "business_name": "Lock It",
                                 "country": "US", "trade_key": "locksmith"})
    a = db.query(Account).one()
    assert (a.trade_key, a.trade) == ("locksmith", "Locksmith")
    assert 'value="locksmith" selected' in client.get("/app/onboarding").text


def test_admin_can_edit_trade_script(client, db):
    from app.models import TradeTemplate
    client.post("/admin/login", data={"password": "admin-pw"})
    assert "Trade scripts" in client.get("/admin/trades").text
    client.post("/admin/trades", data={"key": "plumber", "label": "Plumber", "group": "Plumbing & heating",
                                       "questions": "- Is the water off?", "emergency": "Flooding", "active": "1"})
    db.expire_all()
    assert db.get(TradeTemplate, "plumber").questions == "- Is the water off?"
    client.post("/admin/trades", data={"key": "Window Cleaner", "label": "Window cleaner", "questions": "- How many windows?",
                                       "active": "1"})
    assert db.get(TradeTemplate, "window_cleaner") is not None


def test_login_wrong_password(client, db):
    make_account(db)
    r = client.post("/login", data={"email": "joe@example.com", "password": "nope"})
    assert "Wrong email or password" in r.text
    r = client.post("/login", data={"email": "joe@example.com", "password": "password1"}, follow_redirects=False)
    assert r.headers["location"] == "/app"


def test_dashboard_and_toggle(client, db):
    account = make_account(db)
    db.add(Call(account_id=account.id, kind="agent", status="complete", caller_name="Ann",
                job_description="Boiler not firing", urgency="soon", billed_minutes=3))
    db.commit()
    login(client, account)
    page = client.get("/app")
    assert "Assistant ON" in page.text and "Boiler not firing" in page.text and "3<span" in page.text
    r = client.post("/app/toggle", data={"enabled": "0"})
    assert r.json() == {"agent_enabled": False}
    db.refresh(account)
    assert account.agent_enabled is False


def test_calls_are_private_to_their_owner(client, db):
    a = make_account(db)
    b = make_account(db, email="other@example.com", twilio_number="+15550009999", stripe_customer_id="cus_2")
    call = Call(account_id=b.id, kind="agent")
    db.add(call)
    db.commit()
    login(client, a)
    assert client.get(f"/app/calls/{call.id}").status_code == 404


def test_mark_handled(client, db):
    a = make_account(db)
    call = Call(account_id=a.id, kind="agent", status="complete", caller_name="Ann")
    db.add(call)
    db.commit()
    login(client, a)
    client.get(f"/app/calls/{call.id}")
    client.post(f"/app/calls/{call.id}/handled", data={"handled": "1"})
    db.refresh(call)
    assert call.is_read and call.handled
    assert "Ann" not in client.get("/app?show=open").text


def test_push_subscribe(client, db, no_side_effects):
    a = make_account(db)
    login(client, a)
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "x"}}
    assert client.post("/app/push/subscribe", json=sub).status_code == 200
    assert client.post("/app/push/subscribe", json=sub).status_code == 200
    assert db.query(PushSubscription).count() == 1


def test_password_reset_token_single_use(client, db):
    from app.security import make_reset_token
    a = make_account(db)
    token = make_reset_token(a.id, a.password_hash)
    r = client.post(f"/reset/{token}", data={"password": "newpassword"}, follow_redirects=False)
    assert r.headers["location"] == "/app"
    assert "expired or has already been used" in client.get(f"/reset/{token}").text


def test_forwarding_codes():
    us = {c["key"]: c for c in codes_for("US", "+15557654321")}
    assert us["att"]["on_code"] == "**004*+15557654321#"
    assert us["att"]["on_href"] == "tel:%2A%2A004%2A+15557654321%23"
    assert us["verizon"]["on_code"] == "*715557654321"
    gb = codes_for("GB", "+447700900123")
    assert all(c["off_code"] == "##004#" for c in gb)


def test_phone_helpers():
    assert normalize("07700 900123", "GB") == "+447700900123"
    assert normalize("(555) 123-4567", "US") == "+15551234567"
    assert pretty("+15551234567") == "(555) 123-4567"
    assert pretty("+447700900123") == "07700 900123"


def test_admin_requires_login(client, db):
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"
    client.post("/admin/login", data={"password": "admin-pw"})
    make_account(db)
    assert "Joe&#39;s Plumbing" in client.get("/admin").text
