import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers tables)
from .config import settings
from .db import Base, SessionLocal, engine
from .routes_admin import router as admin_router
from .routes_app import router as app_router
from .routes_webhooks import router as webhooks_router
from .followups import run_forever
from .migrate import add_missing_columns
from .trades import seed_trades
from .web import LoginRequired, RedirectTo

logging.basicConfig(level=logging.INFO)

if not settings.secret_key:
    raise RuntimeError("SECRET_KEY must be set (any long random string)")

Base.metadata.create_all(bind=engine)
add_missing_columns(engine)
with SessionLocal() as _db:
    seed_trades(_db)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Background jobs: missed-call wrap-ups, emergency re-alerts, forwarding
    # nudges, releasing numbers after a cancellation grace period.
    task = asyncio.create_task(run_forever())
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(webhooks_router)
app.include_router(app_router)
app.include_router(admin_router)


@app.exception_handler(LoginRequired)
def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(RedirectTo)
def _redirect(request: Request, exc: RedirectTo):
    return RedirectResponse(exc.url, status_code=303)


# The service worker must be served from the root so it can control /app.
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse("app/static/sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    # Built from settings so renaming the tool renames the installed app too.
    return JSONResponse({
        "name": settings.app_name,
        "short_name": settings.app_name,
        "description": "Your 24/7 AI receptionist - never miss a job while you're working.",
        "start_url": "/app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#12243a",
        "theme_color": "#12243a",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512-maskable.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }, media_type="application/manifest+json")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
