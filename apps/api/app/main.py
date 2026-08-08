from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph import sqlite_checkpointer
from app.api.deps import build_app_state
from app.api.incidents import router as incidents_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        app.state.firefighter = build_app_state(checkpointer)
        yield


app = FastAPI(title="Data Firefighter API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "datahub_mode": settings.datahub_mode,
        "github_configured": bool(settings.github_token and settings.github_demo_repo),
    }
