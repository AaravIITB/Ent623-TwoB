"""App entry point: `uvicorn taxmind_server.main:app --app-dir server` (see README)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .settings import ADMIN_PASSWORD, WEB_DIST
from .db import SessionLocal, init_db
from .auth import ensure_admin
from .api import router

log = logging.getLogger("taxmind")

@asynccontextmanager
async def lifespan(_app):
    init_db()
    with SessionLocal() as db:
        if ensure_admin(db):
            log.warning("Created first user 'admin' with password '%s' - change it under Users.", ADMIN_PASSWORD)
    yield


app = FastAPI(title="TwoB", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.include_router(router)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. The error has been logged."}, status_code=500)


if (WEB_DIST / "index.html").exists():
    if (WEB_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and WEB_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
