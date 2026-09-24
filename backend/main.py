"""FastAPI application: API + Mini App files + (optionally) the Telegram bot in the same process."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import admin, orders, public
from .seed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for sub in ("products", "receipts", "logo"):
        (settings.UPLOAD_DIR / sub).mkdir(parents=True, exist_ok=True)
    await init_db()
    if not settings.SECRET_KEY:
        log.warning("SECRET_KEY is empty - set it in .env")
    if settings.DEV_MODE:
        log.warning("DEV_MODE is ON - never use it on the real server!")
    polling = None
    if settings.RUN_BOT:
        from bot.main import start_polling
        polling = asyncio.create_task(start_polling())
    yield
    if polling:
        from bot.main import stop_polling
        await stop_polling()
        polling.cancel()


app = FastAPI(title=settings.BUSINESS_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    fields = [".".join(str(x) for x in e.get("loc", [])[1:]) for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": {"code": "validation", "fields": fields}})


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")) or path == "/admin":
        response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


app.include_router(public.router)
app.include_router(orders.router)
app.include_router(admin.router)

for _sub in ("products", "receipts", "logo"):
    (settings.UPLOAD_DIR / _sub).mkdir(parents=True, exist_ok=True)

# Public files. NOTE: uploads/receipts is NOT mounted - receipts are private (signed links only).
app.mount("/uploads/products", StaticFiles(directory=settings.UPLOAD_DIR / "products"), name="products")
app.mount("/uploads/logo", StaticFiles(directory=settings.UPLOAD_DIR / "logo"), name="logo")
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(settings.FRONTEND_DIR / "admin.html")


@app.get("/api/{rest:path}", include_in_schema=False)
async def api_404(rest: str):
    raise HTTPException(404, detail={"code": "not_found"})


app.mount("/", StaticFiles(directory=settings.FRONTEND_DIR, html=True), name="frontend")
