from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import applications, jobs, materials, profile, providers, resumes, search, stats
from app.core.db import get_engine
from app.core.i18n import parse_lang, set_lang
from app.search.runner import recover_interrupted


@asynccontextmanager
async def lifespan(app: FastAPI):
    recover_interrupted()  # 上次没跑完的搜索批次标成失败
    yield


class LangMiddleware:
    """读 X-UI-Lang（前端每个请求都带），让这次请求产生的文字用同一种语言。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            header = dict(scope.get("headers") or []).get(b"x-ui-lang", b"").decode("latin-1")
            set_lang(parse_lang(header))
        await self.app(scope, receive, send)


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local(url: str) -> bool:
    try:
        return urlsplit(url).hostname in LOCAL_HOSTS
    except ValueError:  # 畸形的 IPv6 位址
        return False


class LocalOnlyMiddleware:
    """只接受本机页面的请求：挡住别的网站发来的请求（CSRF）和改 DNS 指向本机的网站（DNS rebinding）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            host = headers.get(b"host", b"").decode("latin-1")
            origin = headers.get(b"origin")
            if not _is_local(f"//{host}") or (origin is not None and not _is_local(origin.decode("latin-1"))):
                await JSONResponse({"detail": "Only requests from this computer are allowed."}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(title="job-hunter-agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(LangMiddleware)
    app.add_middleware(LocalOnlyMiddleware)
    app.include_router(providers.router)
    app.include_router(resumes.router)
    app.include_router(profile.router)
    app.include_router(jobs.router)
    app.include_router(materials.router)
    app.include_router(search.router)
    app.include_router(applications.router)
    app.include_router(stats.router)

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
