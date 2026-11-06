import logging
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import billing
from .activation import ensure_number
from .config import settings
from .db import get_db
from .emails import send_email
from .forwarding import codes_for
from .models import Account, Call, PushSubscription, TradeTemplate, WaitlistSignup, utcnow
from .phone import normalize
from .plans import plan_for
from .products import product as get_product
from .products import products
from .push import send_to_account
from .trades import BY_KEY, BY_SLUG, grouped_trades, marketing_trades
from .security import (SESSION_COOKIE, SESSION_MAX_AGE, hash_password, make_reset_token, make_session,
                       read_reset_token, verify_password)
from .web import current_account, is_brand_host, next_setup_step, region_for, render, require_account, require_ready_account

log = logging.getLogger(__name__)
router = APIRouter()


def _login_response(url: str, account: Account) -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(SESSION_COOKIE, make_session(account.id), max_age=SESSION_MAX_AGE, httponly=True,
                    samesite="lax", secure=settings.public_base_url.startswith("https"))
    return resp


# ---------------------------------------------------------------- public

def _brand_home(request: Request, country: str, joined: str, account):
    region = region_for(request, country)
    return render(request, "home.html", account=account, region=region, plan=plan_for(region),
                  products=products(), joined=joined, marketing_page=True, brand_page=True)


def _product_page(request: Request, country: str, account, trade=None, questions=None):
    region = region_for(request, country)
    return render(request, "landing.html", account=account, region=region, plan=plan_for(region), trade=trade,
                  marketing=marketing_trades(), questions=questions, marketing_page=True)


@router.get("/")
def home(request: Request, country: str = "", joined: str = "", account: Account | None = Depends(current_account)):
    """stressfreeservicesystem.com/ -> umbrella page; callcapturer.com/ -> Call Capturer sales page."""
    if is_brand_host(request):
        return _brand_home(request, country, joined, None)
    return _product_page(request, country, account)


@router.get("/tools")
def all_tools(request: Request, country: str = "", joined: str = "",
              account: Account | None = Depends(current_account)):
    """The umbrella page, reachable on any domain (handy for previews)."""
    return _brand_home(request, country, joined, account)


@router.post("/waitlist")
def join_waitlist(request: Request, email: str = Form(...), product: str = Form(...), trade: str = Form(""),
                  db: Session = Depends(get_db)):
    email = email.strip().lower()[:255]
    if "@" in email and get_product(product) and get_product(product).status == "soon":
        exists = db.query(WaitlistSignup).filter(WaitlistSignup.email == email,
                                                 WaitlistSignup.product == product).first()
        if not exists:
            db.add(WaitlistSignup(email=email, product=product, trade=trade.strip()[:120]))
            db.commit()
    back = "/" if is_brand_host(request) else "/tools"
    return RedirectResponse(f"{back}?joined={product}#tools", status_code=303)


@router.get("/for/{slug}")
def trade_page(request: Request, slug: str, country: str = "", account: Account | None = Depends(current_account),
               db: Session = Depends(get_db)):
    t = BY_SLUG.get(slug)
    if t is None:
        raise HTTPException(status_code=404)
    row = db.get(TradeTemplate, t.key)
    questions = [q.lstrip("- ").strip() for q in ((row.questions if row else t.questions) or "").splitlines()
                 if q.strip()]
    return _product_page(request, country, account, trade=t, questions=questions)


# Old URLs from before Call Capturer had its own domain.
@router.get("/call-capturer")
def old_product_page():
    return RedirectResponse("/", status_code=301)


@router.get("/call-capturer/for/{slug}")
def old_trade_page(slug: str):
    return RedirectResponse(f"/for/{slug}", status_code=301)


@router.get("/signup")
def signup_form(request: Request, country: str = "", trade: str = ""):
    return render(request, "signup.html", error=None,
                  form={"country": region_for(request, country), "trade_key": trade if trade in BY_KEY else ""})


@router.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...),
           business_name: str = Form(...), country: str = Form("US"), trade_key: str = Form(""),
           db: Session = Depends(get_db)):
    email = email.strip().lower()
    country = "GB" if country == "GB" else "US"
    form = {"email": email, "business_name": business_name, "country": country, "trade_key": trade_key}
    if "@" not in email or len(email) > 255:
        return render(request, "signup.html", error="Please enter a valid email address.", form=form)
    if len(password) < 8:
        return render(request, "signup.html", error="Password must be at least 8 characters.", form=form)
    if not business_name.strip():
        return render(request, "signup.html", error="Please enter your business name.", form=form)
    if db.query(Account).filter(Account.email == email).first():
        return render(request, "signup.html", error="An account with that email already exists - log in instead.",
                      form=form)
    account = Account(email=email, password_hash=hash_password(password),
                      business_name=business_name.strip()[:200], country=country)
    if trade_key in BY_KEY:  # came from a /for/<trade> page: pre-select their trade
        account.trade_key, account.trade = trade_key, BY_KEY[trade_key].label
    db.add(account)
    db.commit()
    return _login_response("/app/onboarding", account)


@router.get("/login")
def login_form(request: Request):
    return render(request, "login.html", error=None, email="")


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.email == email.strip().lower()).first()
    if account is None or not verify_password(password, account.password_hash):
        return render(request, "login.html", error="Wrong email or password.", email=email)
    return _login_response("/app", account)


@router.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html", sent=False)


@router.post("/forgot")
def forgot(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.email == email.strip().lower()).first()
    if account:
        link = settings.url(f"/reset/{make_reset_token(account.id, account.password_hash)}")
        send_email(account.email, f"Reset your {settings.app_name} password",
                   f"Tap this link to choose a new password (valid for 1 hour):\n\n{link}\n\n"
                   "If you didn't ask for this, ignore this email.")
    # Same response either way, so the form can't be used to discover accounts.
    return render(request, "forgot.html", sent=True)


def _account_for_token(db: Session, token: str) -> Account | None:
    data = read_reset_token(token)
    if not data:
        return None
    account = db.get(Account, data[0])
    if account is None or account.password_hash[-12:] != data[1]:
        return None
    return account


@router.get("/reset/{token}")
def reset_form(request: Request, token: str, db: Session = Depends(get_db)):
    return render(request, "reset.html", token=token, valid=_account_for_token(db, token) is not None, error=None)


@router.post("/reset/{token}")
def reset(request: Request, token: str, password: str = Form(...), db: Session = Depends(get_db)):
    account = _account_for_token(db, token)
    if account is None:
        return render(request, "reset.html", token=token, valid=False, error=None)
    if len(password) < 8:
        return render(request, "reset.html", token=token, valid=True, error="At least 8 characters, please.")
    account.password_hash = hash_password(password)
    db.commit()
    return _login_response("/app", account)


# ---------------------------------------------------------------- signup steps

def _details_ctx(db: Session, account: Account, **extra) -> dict:
    return {"account": account, "trades": grouped_trades(db), **extra}


def _apply_business_details(db: Session, account: Account, form) -> str | None:
    """Copy the business-details form onto the account. Returns an error
    message if something required is missing, else None."""
    def f(name: str, limit: int) -> str:
        return str(form.get(name) or "").strip()[:limit]

    if f("business_name", 200):
        account.business_name = f("business_name", 200)
    account.answer_as = f("answer_as", 200)
    account.assistant_name = f("assistant_name", 60)
    account.voice_gender = "male" if form.get("voice_gender") == "male" else "female"
    account.owner_name = f("owner_name", 120)
    key = f("trade_key", 40)
    trade = db.get(TradeTemplate, key) if key and key != "other" else None
    if trade:
        account.trade_key, account.trade = trade.key, trade.label
    else:
        account.trade_key, account.trade = "other", f("trade_other", 120)
    account.services = f("services", 2000)
    account.service_area = f("service_area", 255)
    account.business_hours = f("business_hours", 255)
    account.owner_phone = normalize(f("owner_phone", 40), account.country)[:32]
    # Callers never see the Call Capturer number (they dial the owner's own
    # number, which forwards), so it doesn't need to be local. For US numbers
    # we still try the owner's own area code first, then fall back to any.
    if account.country == "US" and account.owner_phone.startswith("+1") and len(account.owner_phone) == 12:
        account.area_code = account.owner_phone[2:5]

    missing = []
    if not account.owner_name:
        missing.append("your first name")
    if not account.trade:
        missing.append("your type of business")
    if not account.owner_phone:
        missing.append("your phone number")
    return f"Please fill in {', '.join(missing)}." if missing else None


@router.get("/app/onboarding")
def onboarding_form(request: Request, account: Account = Depends(require_account), db: Session = Depends(get_db)):
    return render(request, "onboarding.html", **_details_ctx(db, account, error=None))


@router.post("/app/onboarding")
async def onboarding(request: Request, account: Account = Depends(require_account), db: Session = Depends(get_db)):
    form = await request.form()
    error = _apply_business_details(db, account, form)
    if error:
        db.rollback()
        db.refresh(account)
        # Re-show what they typed.
        return render(request, "onboarding.html", **_details_ctx(db, _FormView(account, form), error=error))
    account.onboarding_complete = True
    db.commit()
    return RedirectResponse(next_setup_step(account) or "/app/setup", status_code=303)


class _FormView:
    """Wraps an account so a re-rendered form shows the submitted values."""

    def __init__(self, account: Account, form):
        self._a, self._f = account, form

    def __getattr__(self, name):
        alias = {"trade": "trade_other"}.get(name, name)
        if alias in self._f:
            return self._f.get(alias)
        return getattr(self._a, name)


@router.get("/app/subscribe")
def subscribe_page(request: Request, account: Account = Depends(require_account)):
    if not account.onboarding_complete:
        return RedirectResponse("/app/onboarding", status_code=303)
    if account.is_active:
        return RedirectResponse("/app", status_code=303)
    return render(request, "subscribe.html", account=account, plan=plan_for(account.country), error=None)


@router.post("/billing/checkout")
def checkout(request: Request, account: Account = Depends(require_account), db: Session = Depends(get_db)):
    try:
        url = billing.create_checkout_session(account)
    except Exception:
        log.exception("Checkout creation failed for account %s", account.id)
        return render(request, "subscribe.html", account=account, plan=plan_for(account.country),
                      error="Sorry, we couldn't start checkout. Please try again in a minute.")
    db.commit()  # persists a newly created stripe_customer_id
    return RedirectResponse(url, status_code=303)


@router.get("/billing/success")
def checkout_success(session_id: str = "", account: Account = Depends(require_account),
                     db: Session = Depends(get_db)):
    if session_id and not account.is_active:
        try:
            billing.confirm_checkout(db, session_id, account)
        except Exception:
            log.exception("Couldn't confirm checkout %s; the webhook will catch up", session_id)
    ensure_number(db, account)
    return RedirectResponse("/app/setup", status_code=303)


@router.post("/billing/portal")
def billing_portal(account: Account = Depends(require_account)):
    if not account.stripe_customer_id:
        return RedirectResponse("/app/subscribe", status_code=303)
    return RedirectResponse(billing.create_portal_session(account), status_code=303)


@router.get("/app/setup")
def setup_page(request: Request, account: Account = Depends(require_ready_account), db: Session = Depends(get_db)):
    if not account.twilio_number and account.is_active and not account.provisioning_error:
        ensure_number(db, account)
    codes = codes_for(account.country, account.twilio_number) if account.twilio_number else []
    return render(request, "setup.html", account=account, codes=codes)


# ---------------------------------------------------------------- dashboard

def _minutes_this_period(db: Session, account: Account) -> int:
    since = account.current_period_start or (utcnow() - timedelta(days=30))
    total = (db.query(func.coalesce(func.sum(Call.billed_minutes), 0))
             .filter(Call.account_id == account.id, Call.created_at >= since).scalar())
    return int(total or 0)


@router.get("/app")
def dashboard(request: Request, show: str = "open", account: Account = Depends(require_ready_account),
              db: Session = Depends(get_db)):
    q = db.query(Call).filter(Call.account_id == account.id)
    if show == "open":
        q = q.filter(Call.handled.is_(False))
    calls = q.order_by(Call.created_at.desc()).limit(100).all()
    unread = db.query(Call).filter(Call.account_id == account.id, Call.is_read.is_(False)).count()
    plan = plan_for(account.country)
    used = _minutes_this_period(db, account)
    return render(request, "dashboard.html", account=account, calls=calls, show=show, unread=unread, plan=plan,
                  minutes_used=used, overage=max(0, used - plan.included_minutes))


@router.post("/app/toggle")
def toggle(enabled: str = Form(...), account: Account = Depends(require_ready_account),
           db: Session = Depends(get_db)):
    account.agent_enabled = enabled in ("1", "true", "on")
    db.commit()
    return JSONResponse({"agent_enabled": account.agent_enabled})


def _own_call(db: Session, account: Account, call_id: int) -> Call:
    call = db.get(Call, call_id)
    if call is None or call.account_id != account.id:
        raise HTTPException(status_code=404)
    return call


@router.get("/app/calls/{call_id}")
def call_detail(request: Request, call_id: int, account: Account = Depends(require_ready_account),
                db: Session = Depends(get_db)):
    call = _own_call(db, account, call_id)
    if not call.is_read:
        call.is_read = True
        db.commit()
    return render(request, "call_detail.html", account=account, call=call)


@router.post("/app/calls/{call_id}/handled")
def mark_handled(call_id: int, handled: str = Form("1"), account: Account = Depends(require_ready_account),
                 db: Session = Depends(get_db)):
    call = _own_call(db, account, call_id)
    call.handled = handled == "1"
    db.commit()
    return RedirectResponse("/app" if call.handled else f"/app/calls/{call_id}", status_code=303)


@router.get("/app/calls/{call_id}/recording")
def call_recording(call_id: int, account: Account = Depends(require_ready_account), db: Session = Depends(get_db)):
    call = _own_call(db, account, call_id)
    if not call.recording_url:
        raise HTTPException(status_code=404)
    if "api.twilio.com" not in call.recording_url:
        return RedirectResponse(call.recording_url)  # Retell recordings are directly playable
    # Twilio recordings need our credentials, so stream them through.
    resp = httpx.get(call.recording_url + ".mp3", auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                     timeout=20, follow_redirects=True)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Recording not available yet")
    return Response(resp.content, media_type="audio/mpeg")


# ---------------------------------------------------------------- settings

@router.get("/app/settings")
def settings_page(request: Request, saved: int = 0, account: Account = Depends(require_ready_account),
                  db: Session = Depends(get_db)):
    return render(request, "settings.html", **_details_ctx(db, account, saved=bool(saved), error=None))


@router.post("/app/settings")
async def save_settings(request: Request, account: Account = Depends(require_ready_account),
                        db: Session = Depends(get_db)):
    form = await request.form()
    error = _apply_business_details(db, account, form)
    if error:
        db.rollback()
        db.refresh(account)
        return render(request, "settings.html",
                      **_details_ctx(db, _FormView(account, form), saved=False, error=error))
    db.commit()
    return RedirectResponse("/app/settings?saved=1", status_code=303)


# ---------------------------------------------------------------- push

@router.post("/app/push/subscribe")
async def push_subscribe(request: Request, account: Account = Depends(require_account),
                         db: Session = Depends(get_db)):
    data = await request.json()
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail="Invalid subscription")
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, account_id=account.id, p256dh=keys["p256dh"], auth=keys["auth"])
        db.add(sub)
    else:
        sub.account_id, sub.p256dh, sub.auth = account.id, keys["p256dh"], keys["auth"]
    db.commit()
    return {"ok": True}


@router.post("/app/push/test")
def push_test(account: Account = Depends(require_account), db: Session = Depends(get_db)):
    sent = send_to_account(db, account, "Notifications are on ✅",
                           "You'll get a notification like this for every call.")
    return {"sent": sent}
