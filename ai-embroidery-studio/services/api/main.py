"""FastAPI application. Run: uvicorn services.api.main:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.core.db import init_db
from services.core.queue import recover_jobs
from services.core.settings import get_settings

from .routers import projects


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if get_settings().queue_mode == "thread":
        requeued, failed = recover_jobs()
        print(f"job recovery: requeued={requeued} interrupted={failed}", flush=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Embroidery Studio API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Dev-User"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "authMode": settings.auth_mode, "queueMode": settings.queue_mode}

    app.include_router(projects.router)
    return app


app = create_app()
