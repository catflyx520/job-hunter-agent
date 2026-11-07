from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api import jobs, materials, profile, providers, resumes, search
from app.core.db import get_engine
from app.search.runner import recover_interrupted


@asynccontextmanager
async def lifespan(app: FastAPI):
    recover_interrupted()  # 上次没跑完的搜索批次标成失败
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="job-hunter-agent", version="0.1.0", lifespan=lifespan)
    app.include_router(providers.router)
    app.include_router(resumes.router)
    app.include_router(profile.router)
    app.include_router(jobs.router)
    app.include_router(materials.router)
    app.include_router(search.router)

    @app.get("/api/health")
    def health():
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            db = "ok"
        except Exception:  # noqa: BLE001
            db = "unavailable"
        return {"status": "ok", "database": db}

    return app


app = create_app()
