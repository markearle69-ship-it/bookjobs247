"""Operator panel: customers, UK number pool, and fix-it buttons."""

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import billing
from .activation import ensure_number
from .config import settings
from .db import get_db
from .models import Account, Call, PoolNumber, TradeTemplate, utcnow
from .phone import normalize
from .security import ADMIN_COOKIE, ADMIN_MAX_AGE, make_admin_session, read_admin_session
from .telephony import POOL_COOLDOWN, ProvisioningError, lookup_owned_number
from .web import render

router = APIRouter(prefix="/admin")


def _is_admin(request: Request) -> bool:
    return read_admin_session(request.cookies.get(ADMIN_COOKIE))


def _go(msg: str = "") -> RedirectResponse:
    return RedirectResponse(f"/admin?msg={msg}" if msg else "/admin", status_code=303)


@router.get("/login")
def admin_login_form(request: Request):
    return render(request, "admin/login.html", error=None)


@router.post("/login")
def admin_login(request: Request, password: str = Form(...)):
    if not settings.admin_password or not hmac.compare_digest(password, settings.admin_password):
        return render(request, "admin/login.html", error="Wrong password.")
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(ADMIN_COOKIE, make_admin_session(), max_age=ADMIN_MAX_AGE, httponly=True, samesite="lax",
                    secure=settings.public_base_url.startswith("https"))
    return resp


@router.get("")
def admin_home(request: Request, msg: str = "", db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    accounts = db.query(Account).order_by(Account.created_at.desc()).all()
    since = utcnow() - timedelta(days=30)
    minutes = dict(db.query(Call.account_id, func.sum(Call.billed_minutes))
                   .filter(Call.created_at >= since).group_by(Call.account_id).all())
    calls = dict(db.query(Call.account_id, func.count(Call.id))
                 .filter(Call.created_at >= since).group_by(Call.account_id).all())
    pool = db.query(PoolNumber).order_by(PoolNumber.id).all()
    cutoff = utcnow() - POOL_COOLDOWN
    pool_free = sum(1 for p in pool if p.account_id is None and (p.released_at is None or p.released_at <= cutoff))
    unreported = db.query(Call).filter(Call.kind == "agent", Call.usage_reported.is_(False),
                                       Call.duration_seconds > 0).count()
    active = sum(1 for a in accounts if a.is_active)
    return render(request, "admin/home.html", accounts=accounts, minutes=minutes, calls=calls, pool=pool,
                  pool_free=pool_free, unreported=unreported, active=active, msg=msg)


@router.post("/pool")
def add_pool_number(request: Request, phone_number: str = Form(...), db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    number = normalize(phone_number, "GB")
    if db.query(PoolNumber).filter(PoolNumber.phone_number == number).first():
        return _go(f"{number} is already in the pool")
    try:
        sid = lookup_owned_number(number)
    except ProvisioningError as exc:
        return _go(str(exc))
    db.add(PoolNumber(phone_number=number, twilio_sid=sid, country="GB"))
    db.commit()
    # Someone may be waiting on an empty pool.
    waiting = db.query(Account).filter(Account.country == "GB", Account.twilio_number.is_(None),
                                       Account.provisioning_error.is_not(None)).all()
    for account in waiting:
        if ensure_number(db, account):
            break
    return _go(f"Added {number}")


@router.post("/accounts/{account_id}/retry")
def retry_provisioning(request: Request, account_id: int, db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    account = db.get(Account, account_id)
    if account:
        account.provisioning_error = None
        ok = ensure_number(db, account)
        return _go("Number assigned" if ok else f"Still failing: {account.provisioning_error or 'not active'}")
    return _go()


@router.post("/usage/retry")
def retry_usage(request: Request, db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    pending = db.query(Call).filter(Call.kind == "agent", Call.usage_reported.is_(False),
                                    Call.duration_seconds > 0).all()
    for call in pending:
        billing.report_usage(db, call)
    left = sum(1 for c in pending if not c.usage_reported)
    return _go(f"Reported {len(pending) - left}, {left} still failing")


# ---------------------------------------------------------------- trade scripts

@router.get("/trades")
def trades_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    rows = db.query(TradeTemplate).order_by(TradeTemplate.sort_order).all()
    in_use = dict(db.query(Account.trade_key, func.count(Account.id)).group_by(Account.trade_key).all())
    return render(request, "admin/trades.html", trades=rows, in_use=in_use, msg=msg)


@router.post("/trades")
def save_trade(request: Request, key: str = Form(...), label: str = Form(...), group: str = Form(""),
               questions: str = Form(""), emergency: str = Form(""), active: str = Form(""),
               db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    key = "".join(ch for ch in key.strip().lower().replace(" ", "_") if ch.isalnum() or ch == "_")[:40]
    if not key or key == "other" or not label.strip():
        return RedirectResponse("/admin/trades?msg=Key and label are required", status_code=303)
    row = db.get(TradeTemplate, key)
    if row is None:
        last = db.query(func.max(TradeTemplate.sort_order)).scalar() or 0
        row = TradeTemplate(key=key, sort_order=last + 10)
        db.add(row)
    row.label, row.group = label.strip()[:120], group.strip()[:120]
    row.questions, row.emergency = questions.strip(), emergency.strip()
    row.active = active == "1"
    db.commit()
    return RedirectResponse(f"/admin/trades?msg=Saved {row.label}#t-{key}", status_code=303)
