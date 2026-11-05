import logging

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers tables)
from .config import settings
from .db import Base, SessionLocal, engine
from .routes_admin import router as admin_router
from .routes_app import router as app_router
from .routes_webhooks import router as webhooks_router
from .trades import seed_trades
from .web import LoginRequired, RedirectTo

logging.basicConfig(level=logging.INFO)

if not settings.secret_key:
    raise RuntimeError("SECRET_KEY must be set (any long random string)")

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    seed_trades(_db)

app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)
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
    return FileResponse("app/static/manifest.webmanifest", media_type="application/manifest+json")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
