"""Shared bits for HTML routes: templates and the logged-in-owner dependency."""

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Account
from .phone import pretty
from .plans import plan_for
from .security import SESSION_COOKIE, read_session

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["pretty"] = pretty
templates.env.globals["settings"] = settings
templates.env.globals["plan_for"] = plan_for


class LoginRequired(Exception):
    pass


class RedirectTo(Exception):
    def __init__(self, url: str):
        self.url = url


def current_account(request: Request, db: Session = Depends(get_db)) -> Account | None:
    account_id = read_session(request.cookies.get(SESSION_COOKIE))
    return db.get(Account, account_id) if account_id else None


def require_account(account: Account | None = Depends(current_account)) -> Account:
    if account is None:
        raise LoginRequired()
    return account


def next_setup_step(account: Account) -> str | None:
    """Where an owner who hasn't finished signing up should be sent."""
    if not account.onboarding_complete:
        return "/app/onboarding"
    if not account.is_active and account.subscription_status in ("none", "incomplete", "incomplete_expired",
                                                                 "canceled"):
        return "/app/subscribe"
    return None


def require_ready_account(account: Account = Depends(require_account)) -> Account:
    step = next_setup_step(account)
    if step:
        raise RedirectTo(step)
    return account


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)
