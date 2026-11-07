from fastapi import FastAPI
from sqlalchemy import text

from app.api import profile, providers, resumes
from app.core.db import get_engine


def create_app() -> FastAPI:
    app = FastAPI(title="job-hunter-agent", version="0.1.0")
    app.include_router(providers.router)
    app.include_router(resumes.router)
    app.include_router(profile.router)

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
