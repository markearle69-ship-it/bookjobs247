"""Make sure every call ends up "complete" and notified, even when a webhook
we were counting on never arrives (caller hung up before the beep, Retell's
analysis failed, etc.)."""

import asyncio
import logging

from .db import SessionLocal
from .models import Call
from .push import notify_call, remind_emergency

log = logging.getLogger(__name__)

MISSED_SUMMARY = "Caller hung up without leaving a message."


def finalize(call_id: int) -> None:
    db = SessionLocal()
    try:
        call = db.get(Call, call_id)
        if call is None or call.notified:
            return
        if call.kind == "voicemail" and not call.recording_url:
            call.summary = call.summary or MISSED_SUMMARY
        elif call.kind == "agent" and call.status == "in_progress" and not call.transcript:
            call.summary = call.summary or MISSED_SUMMARY
        call.status = "complete"
        db.commit()
        notify_call(db, call)
    except Exception:
        log.exception("Follow-up for call %s failed", call_id)
    finally:
        db.close()


def schedule(call_id: int, delay_seconds: float) -> None:
    async def _run():
        await asyncio.sleep(delay_seconds)
        await asyncio.to_thread(finalize, call_id)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:  # no event loop (scripts) - just run it now
        finalize(call_id)


def _remind(call_id: int) -> None:
    db = SessionLocal()
    try:
        call = db.get(Call, call_id)
        if call is not None:
            remind_emergency(db, call)
    except Exception:
        log.exception("Emergency reminder for call %s failed", call_id)
    finally:
        db.close()


def schedule_emergency_reminder(call_id: int, delay_seconds: float) -> None:
    async def _run():
        await asyncio.sleep(delay_seconds)
        await asyncio.to_thread(_remind, call_id)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass  # no event loop (scripts/tests) - reminders only matter in the running app
