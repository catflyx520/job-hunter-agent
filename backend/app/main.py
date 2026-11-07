from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import profile, providers, resumes
from app.core.config import get_settings
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

    # docker 模式：后端直接提供前端打包档；原生模式由 Vite dev server 提供
    static_dir = get_settings().static_dir
    if static_dir and static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            file = static_dir / path
            if path and file.is_file() and static_dir in file.resolve().parents:
                return FileResponse(file)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
