"""F1 模型连接：provider CRUD、测试连接、任务路由、本机 CLI 状态与页面登录。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import SecretKeyMissing, encrypt_secret, last4
from app.llm import cli_auth, registry
from app.llm.base import DEFAULT_CAPABILITIES, LLMError, Message
from app.models import TASKS, TaskRoute
from app.models import LLMProvider as ProviderRow
from app.schemas.provider import (
    CliInfo,
    CliLoginOut,
    CliStatusOut,
    LoginCodeIn,
    ProviderIn,
    ProviderOut,
    ProviderUpdate,
    TaskRouteIn,
    TaskRouteOut,
    TestResult,
)

router = APIRouter(prefix="/api", tags=["providers"])

CLI_NOTICE = (
    "此模式使用你自己的订阅额度，仅供个人本地使用，额度和使用规则以 Anthropic / OpenAI 的条款为准。"
    "app 只以子进程调用你本机的 CLI；登录由 CLI 自己完成并保存凭证，app 不读取、不保存任何 token，"
    "验证码只转交给 CLI、不会记录。"
)
NEEDS_KEY = {"openai", "anthropic"}
NEEDS_URL = {"openai_compatible"}


def _out(row: ProviderRow) -> ProviderOut:
    return ProviderOut.model_validate(
        {
            **{c: getattr(row, c) for c in ProviderOut.model_fields if hasattr(row, c)},
            "has_api_key": row.api_key_encrypted is not None,
        }
    )


def _get(db: Session, provider_id: uuid.UUID) -> ProviderRow:
    row = db.get(ProviderRow, provider_id)
    if row is None:
        raise HTTPException(404, "找不到这个模型连接")
    return row


def _set_key(row: ProviderRow, key: str | None) -> None:
    if key is None:
        return
    if key == "":
        row.api_key_encrypted, row.api_key_last4 = None, None
        return
    try:
        row.api_key_encrypted = encrypt_secret(key)
    except SecretKeyMissing as exc:
        raise HTTPException(400, str(exc)) from exc
    row.api_key_last4 = last4(key)


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db)):
    return [_out(r) for r in db.scalars(select(ProviderRow).order_by(ProviderRow.created_at))]


@router.post("/providers", response_model=ProviderOut, status_code=201)
def create_provider(body: ProviderIn, db: Session = Depends(get_db)):
    if body.kind in NEEDS_KEY and not body.api_key:
        raise HTTPException(422, "这个类型需要 API key")
    if body.kind in NEEDS_URL and not body.base_url:
        raise HTTPException(422, "OpenAI 兼容端点需要填写 base_url")
    row = ProviderRow(
        kind=body.kind,
        name=body.name,
        base_url=body.base_url or ("http://localhost:11434" if body.kind == "ollama" else None),
        default_model=body.default_model,
        capabilities=(body.capabilities or DEFAULT_CAPABILITIES[body.kind]).model_dump(),
        enabled=body.enabled,
    )
    _set_key(row, body.api_key)
    db.add(row)
    db.flush()
    db.refresh(row)
    return _out(row)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: uuid.UUID, body: ProviderUpdate, db: Session = Depends(get_db)):
    row = _get(db, provider_id)
    data = body.model_dump(exclude_unset=True)
    for field in ("name", "base_url", "default_model", "enabled"):
        if field in data:
            setattr(row, field, data[field])
    if body.capabilities is not None:
        row.capabilities = body.capabilities.model_dump()
    _set_key(row, body.api_key)
    db.flush()
    db.refresh(row)
    return _out(row)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: uuid.UUID, db: Session = Depends(get_db)):
    row = _get(db, provider_id)
    used = db.scalars(select(TaskRoute.task).where(TaskRoute.provider_id == provider_id)).all()
    if used:
        raise HTTPException(409, f"这个连接仍被任务路由使用（{', '.join(used)}），请先修改路由。")
    db.delete(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "这个连接仍被使用，无法删除。") from exc


@router.post("/providers/{provider_id}/test", response_model=TestResult)
def test_provider(provider_id: uuid.UUID, db: Session = Depends(get_db)):
    row = _get(db, provider_id)
    row.last_checked_at = datetime.now(UTC)
    try:
        provider = registry.build_provider(row)
        result = provider.generate(
            [Message("user", "Reply with the single word: ok")],
        )
        row.last_check_error = None
        return TestResult(ok=True, message="连线成功", sample=result.text.strip()[:200])
    except (LLMError, SecretKeyMissing) as exc:
        row.last_check_error = str(exc)
        return TestResult(ok=False, message=str(exc))


@router.get("/providers/{provider_id}/models", response_model=list[str])
def list_models(provider_id: uuid.UUID, db: Session = Depends(get_db)):
    row = _get(db, provider_id)
    try:
        return registry.build_provider(row).list_models()
    except (LLMError, SecretKeyMissing) as exc:
        raise HTTPException(502, str(exc)) from exc


def _check_cli(name: str) -> cli_auth.CliName:
    if name not in ("claude", "codex"):
        raise HTTPException(404, "未知的 CLI")
    return name  # type: ignore[return-value]


def _login_out() -> CliLoginOut | None:
    snap = cli_auth.login_manager.snapshot()
    return CliLoginOut(**snap.__dict__) if snap else None


@router.get("/cli-status", response_model=CliInfo)
def cli_status():
    clis = [CliStatusOut(**cli_auth.auth_info(name).__dict__) for name in ("claude", "codex")]
    return CliInfo(clis=clis, notice=CLI_NOTICE, login=_login_out())


@router.post("/cli/{name}/login", response_model=CliLoginOut)
def cli_login(name: str):
    cli = _check_cli(name)
    try:
        cli_auth.login_manager.start(cli)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return _login_out()


@router.get("/cli/login", response_model=CliLoginOut | None)
def cli_login_state():
    return _login_out()


@router.post("/cli/login/code")
def cli_login_code(body: LoginCodeIn):
    return {"status": cli_auth.login_manager.submit_code(body.code)}


@router.post("/cli/login/cancel", status_code=204)
def cli_login_cancel():
    cli_auth.login_manager.cancel()


@router.post("/cli/{name}/logout")
def cli_logout(name: str):
    ok, message = cli_auth.logout(_check_cli(name))
    return {"ok": ok, "message": message}


# ---------- 任务路由 ----------


@router.get("/task-routes", response_model=list[TaskRouteOut])
def list_routes(db: Session = Depends(get_db)):
    routes = {r.task: r for r in db.scalars(select(TaskRoute))}
    out = []
    for task in TASKS:
        r = routes.get(task)
        out.append(
            TaskRouteOut(
                task=task,
                label=registry.TASK_LABELS[task],
                provider_id=r.provider_id if r else None,
                model=r.model if r else None,
                params=r.params if r else None,
            )
        )
    return out


@router.put("/task-routes/{task}", response_model=TaskRouteOut)
def set_route(task: str, body: TaskRouteIn, db: Session = Depends(get_db)):
    if task not in TASKS:
        raise HTTPException(404, "未知的任务")
    provider = _get(db, body.provider_id)
    if task == "embedding" and not registry.supports_embedding(provider.kind):
        raise HTTPException(422, "这个连接不支援 embedding，请选 OpenAI、OpenAI 兼容端点或 Ollama。")
    route = db.get(TaskRoute, task) or TaskRoute(task=task)
    route.provider_id, route.model, route.params = body.provider_id, body.model, body.params
    db.add(route)
    db.flush()
    return TaskRouteOut(
        task=task,
        label=registry.TASK_LABELS[task],
        provider_id=route.provider_id,
        model=route.model,
        params=route.params,
    )


@router.delete("/task-routes/{task}", status_code=204)
def clear_route(task: str, db: Session = Depends(get_db)):
    route = db.get(TaskRoute, task)
    if route is not None:
        db.delete(route)
