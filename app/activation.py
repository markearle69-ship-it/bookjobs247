"""What happens once a customer has paid: get them a number."""

import logging

from sqlalchemy.orm import Session

from .config import settings
from .emails import alert_admin, send_email
from .models import Account
from .phone import pretty
from .telephony import ProvisioningError, provision_number

log = logging.getLogger(__name__)


def ensure_number(db: Session, account: Account) -> bool:
    """Idempotent. Returns True if the account has a number afterwards."""
    if account.twilio_number:
        return True
    if not account.is_active:
        return False
    try:
        number = provision_number(db, account)
    except ProvisioningError as exc:
        account.provisioning_error = str(exc)
        db.commit()
        log.error("Provisioning failed for account %s: %s", account.id, exc)
        alert_admin("Number provisioning failed",
                    f"Account #{account.id} ({account.business_name}, {account.country}): {exc}\n"
                    f"Fix it, then click Retry in {settings.url('/admin')}")
        return False
    send_email(
        account.email,
        f"Your {settings.app_name} number is ready",
        f"Hi {account.owner_name or 'there'},\n\n"
        f"Your {settings.app_name} number is {pretty(number)}.\n\n"
        f"One last step: set your phone to forward missed calls to it. The app shows you exactly how,\n"
        f"with one-tap buttons: {settings.url('/app/setup')}\n\n"
        f"Then add the app to your home screen and turn on notifications so you see every call.\n",
    )
    return True
