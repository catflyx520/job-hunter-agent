"""邮件同步 API：Gmail 只读连接、同步、summary、处理需要确认的信。app 不发信、不删信、不改标签。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.i18n import tr
from app.core.security import encrypt_secret
from app.llm.base import LLMError
from app.mail import gmail, sync
from app.mail.claude_gmail import ClaudeGmail
from app.mail.match import can_bulk_create, resolve
from app.models import EmailMessage, EmailSync, Integration

router = APIRouter(prefix="/api/email", tags=["email"])


class GmailStatus(BaseModel):
    connected: bool
    email: str | None = None
    connected_at: str | None = None
    client_id: str | None = None
    has_client_secret: bool = False
    mode: Literal["claude_cli", "oauth"] | None = None  # 经本机 Claude CLI 的连接器读信，或自己的 Google client
    last_sync: dict | None = None


class AuthUrlIn(BaseModel):
    client_id: str | None = Field(None, max_length=300)
    client_secret: str | None = Field(None, max_length=300)
    redirect_uri: str = Field(max_length=500)


class BulkIn(BaseModel):
    action: Literal["create", "ignore"]
    ids: list[str] = Field(max_length=1000)


class ResolveIn(BaseModel):
    action: Literal["link", "create", "ignore"]
    job_id: uuid.UUID | None = None
    company: str = Field("", max_length=200)
    title: str = Field("", max_length=300)


def _latest(db: Session) -> EmailSync | None:
    return db.scalar(select(EmailSync).order_by(EmailSync.started_at.desc()))


@router.get("/gmail", response_model=GmailStatus)
def gmail_status(db: Session = Depends(get_db)):
    row = sync.gmail_row(db)
    last = _latest(db)
    last_out = {"id": str(last.id), "status": last.status, "started_at": last.started_at.isoformat()} if last else None
    if row is None:
        return GmailStatus(connected=False, last_sync=last_out)
    cfg = row.config or {}
    if cfg.get("mode") == "claude_cli":
        return GmailStatus(connected=True, mode="claude_cli", connected_at=cfg.get("connected_at"), last_sync=last_out)
    secret = sync.gmail_secret(row)
    return GmailStatus(
        connected=bool(secret.get("refresh_token")),
        mode="oauth" if secret.get("refresh_token") else None,
        email=cfg.get("email"),
        connected_at=cfg.get("connected_at"),
        client_id=cfg.get("client_id"),
        has_client_secret=bool(secret.get("client_secret")),
        last_sync=last_out,
    )


@router.post("/gmail/cli", response_model=GmailStatus)
def gmail_use_claude_cli(db: Session = Depends(get_db)):
    """改用本机 Claude CLI 已连好的 Gmail 连接器读信：先实际测一次，通过才保存。app 不保存任何 token。"""
    try:
        ClaudeGmail().check()
    except LLMError as exc:
        raise HTTPException(409, str(exc)) from exc
    row = sync.gmail_row(db)
    if row is None:
        row = Integration(kind="gmail", config={}, enabled=True)
        db.add(row)
    elif token := sync.gmail_secret(row).get("refresh_token"):
        gmail.revoke(token)  # 原本用自己的 Google client：换方式就撤销旧授权
    row.config = {"mode": "claude_cli", "connected_at": datetime.now(UTC).isoformat()}
    row.secret_encrypted = None
    row.enabled = True
    db.flush()
    return gmail_status(db)


@router.post("/gmail/auth-url")
def gmail_auth_url(body: AuthUrlIn, db: Session = Depends(get_db)):
    row = sync.gmail_row(db)
    saved = sync.gmail_secret(row) if row else {}
    client_id = (body.client_id or "").strip() or (row.config.get("client_id") if row else "")
    client_secret = (body.client_secret or "").strip() or saved.get("client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(422, tr("请填写 Google OAuth client ID 与 client secret。"))
    try:
        return {"url": gmail.start_auth(client_id, client_secret, body.redirect_uri)}
    except gmail.GmailError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/gmail/callback")
def gmail_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    redirect = gmail.pending_redirect(state)
    origin = f"{urlsplit(redirect).scheme}://{urlsplit(redirect).netloc}" if redirect else ""
    try:
        if error:
            gmail._pending.pop(state, None)
            raise gmail.GmailError(tr("你在 Google 授权页取消了授权。"))
        got = gmail.finish_auth(state, code)
    except gmail.GmailError as exc:
        return RedirectResponse(f"{origin}/settings?view=email&email_error={quote(str(exc))}", status_code=303)
    row = sync.gmail_row(db)
    if row is None:
        row = Integration(kind="gmail", config={}, enabled=True)
        db.add(row)
    row.config = {
        "client_id": got["client_id"],
        "email": got["email"],
        "scope": gmail.SCOPE,
        "connected_at": datetime.now(UTC).isoformat(),
    }
    row.secret_encrypted = encrypt_secret(
        json.dumps({"client_secret": got["client_secret"], "refresh_token": got["refresh_token"]})
    )
    row.enabled = True
    db.flush()
    return RedirectResponse(f"{origin}/settings?view=email&email=connected", status_code=303)


@router.post("/gmail/test")
def gmail_test(db: Session = Depends(get_db)):
    try:
        client, _ = sync.gmail_client(db)
        if isinstance(client, ClaudeGmail):
            client.check()
            return {"email": None}
        return {"email": client.profile_email()}
    except LLMError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/gmail", status_code=204)
def gmail_disconnect(db: Session = Depends(get_db)):
    """撤销 Google 授权并删除本机保存的授权；处理过的信与状态历史保留（是证据）。"""
    row = sync.gmail_row(db)
    if row is None:
        return
    token = sync.gmail_secret(row).get("refresh_token")
    if token:
        gmail.revoke(token)
    db.delete(row)
    db.flush()


@router.post("/sync", status_code=201)
def start_sync(db: Session = Depends(get_db)):
    try:
        sync.gmail_client(db)  # 没连接就直接告诉用户
        s = sync.create_sync(db)
    except gmail.GmailError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()  # 背景执行绪要读得到
    sync.start_sync(s.id)
    return {"id": str(s.id)}


@router.get("/syncs/latest")
def latest_sync(db: Session = Depends(get_db)):
    s = _latest(db)
    if s is None:
        return {"id": None, "status": None, "summary": None, "needs_review": sync.needs_review(db)}
    return sync.sync_out(db, s)


@router.get("/syncs/{sync_id}")
def get_sync(sync_id: uuid.UUID, db: Session = Depends(get_db)):
    s = db.get(EmailSync, sync_id)
    if s is None:
        raise HTTPException(404, tr("找不到这次同步"))
    return sync.sync_out(db, s)


@router.post("/messages/{message_id}/resolve")
def resolve_message(message_id: str, body: ResolveIn, db: Session = Depends(get_db)):
    row = db.get(EmailMessage, message_id)
    if row is None:
        raise HTTPException(404, tr("找不到这封信"))
    if row.outcome != "needs_review":
        raise HTTPException(409, tr("这封信已经处理过了。"))
    if body.action == "create" and not (body.company.strip() and body.title.strip()):
        raise HTTPException(422, tr("请填写公司与职称。"))
    if body.action != "ignore" and row.kind == "not_evidence":
        raise HTTPException(422, tr("模型没能判断这封信是什么，请在 Gmail 看过之后自己改职位状态，再按「忽略」。"))
    if body.action == "link" and body.job_id is None:
        raise HTTPException(422, tr("请选择要对应的职位。"))
    try:
        d = resolve(db, row, body.action, body.job_id, body.company.strip(), body.title.strip())
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "message": sync.message_out(row),
        "decision": {
            "outcome": d.outcome,
            "job_id": str(d.job_id) if d.job_id else None,
            "from": d.from_status,
            "to": d.to_status,
            "rechecked": d.rechecked,
        },
    }


@router.post("/messages/resolve-bulk")
def resolve_bulk(body: BulkIn, db: Session = Depends(get_db)):
    """一次处理多封需要确认的信：全部忽略，或把「信里写明公司与职称、找不到对应职位」的新建为职位。
    不符合条件、已经处理过（包括被同公司的规则顺便处理掉）的跳过。"""
    done = skipped = 0
    for mid in body.ids:
        row = db.get(EmailMessage, mid)
        if row is None or row.outcome != "needs_review":
            skipped += 1
        elif body.action == "ignore":
            resolve(db, row, "ignore")
            done += 1
        elif can_bulk_create(db, row):
            resolve(db, row, "create", company=row.company, title=row.title)
            done += 1
        else:
            skipped += 1
    return {"resolved": done, "skipped": skipped}
