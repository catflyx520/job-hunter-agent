"""邮件同步：建立同步、背景执行（读信 → 分类 → 对上职位）、summary、需要确认清单。"""

from __future__ import annotations

import contextvars
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.i18n import tr
from app.core.security import decrypt_secret
from app.llm.base import LLMError
from app.llm.registry import provider_for_task
from app.mail.classify import BATCH, MailClassification, classify, classify_batch
from app.mail.claude_gmail import ClaudeGmail
from app.mail.gmail import QUERY_VERSION, GmailClient, GmailError, search_query
from app.mail.match import can_bulk_create, candidate_jobs, decide_and_apply, reason_text
from app.models import Application, ApplicationEvent, EmailMessage, EmailSync, Integration, Job

FIRST_DAYS = 30
OVERLAP_DAYS = 3
MAX_NEW = 200
LIST_LIMIT = 2000  # Gmail 列信一次最多拿几个 id


def gmail_row(db: Session) -> Integration | None:
    return db.scalar(select(Integration).where(Integration.kind == "gmail"))


def gmail_secret(row: Integration) -> dict:
    return json.loads(decrypt_secret(row.secret_encrypted)) if row.secret_encrypted else {}


def gmail_client(db: Session) -> tuple[GmailClient | ClaudeGmail, str]:
    row = gmail_row(db)
    if row is not None and (row.config or {}).get("mode") == "claude_cli":
        return ClaudeGmail(), row.config.get("email", "")
    secret = gmail_secret(row) if row else {}
    if row is None or not secret.get("refresh_token"):
        raise GmailError(tr("请先到 Settings 连接 Gmail。"))
    return GmailClient(row.config["client_id"], secret["client_secret"], secret["refresh_token"]), row.config.get(
        "email", ""
    )


def create_sync(db: Session) -> EmailSync:
    if db.scalar(select(EmailSync.id).where(EmailSync.status == "running")):
        raise GmailError(tr("已经有一个邮件同步正在进行。"))
    last = db.scalar(
        select(EmailSync.window_before)
        .where(
            EmailSync.status == "completed",
            EmailSync.window_before.is_not(None),
            # 用旧查询条件读过的不算：条件换了要从头（最近 30 天）再读一次
            EmailSync.summary["query_version"].as_integer() == QUERY_VERSION,
        )
        .order_by(EmailSync.started_at.desc())
    )
    now = datetime.now(UTC)
    after = last - timedelta(days=OVERLAP_DAYS) if last else now - timedelta(days=FIRST_DAYS)
    sync = EmailSync(status="running", window_after=after, started_at=now)
    db.add(sync)
    db.flush()
    return sync


def _excerpt(evidence: str, text: str, kind: str, reason: str | None) -> str | None:
    """证据原句；原句没核对过（有 reason）就改存信的开头，不把模型的话当成信里的原文。"""
    if kind == "not_evidence" and reason is None:
        return None
    quote = evidence.strip() if reason is None else ""
    return (quote or " ".join(text.split()))[:500]


def _unknown(db: Session, ids: list[tuple[str, str]]) -> list[str]:
    known = set(db.scalars(select(EmailMessage.id).where(EmailMessage.id.in_([i for i, _ in ids]))))
    return [i for i, _ in ids if i not in known]


def _list_new(db: Session, client: GmailClient, sync: EmailSync) -> tuple[list[str], datetime | None]:
    """回传还没处理过的信（旧到新）与缩小后的窗口终点。
    Gmail 一次最多列 LIST_LIMIT 封、而且是最新的那批：列满时先读比那批更旧、还没处理过的信，下次再接着读。"""
    ids = client.list_ids(search_query(sync.window_after), limit=LIST_LIMIT)
    before = None
    # more：经 Claude CLI 搜索时翻页有上限，还有下一页就当作列满
    while ids and (len(ids) >= LIST_LIMIT or getattr(client, "more", False)):
        mid = ids[-1][0]
        oldest = client.received_at(mid) if hasattr(client, "received_at") else client.get(mid).received_at
        if before is not None and oldest >= before:
            break
        older = client.list_ids(search_query(sync.window_after, oldest), limit=LIST_LIMIT)
        if not _unknown(db, older):
            break
        ids, before = older, oldest
    return list(reversed(_unknown(db, ids))), before


def _classify_all(provider, msgs: list) -> list[tuple[MailClassification, str | None]]:
    """一次分类一批；整批失败就逐封分类，单封失败的列为需要确认（不挡住其他信）。"""
    try:
        return classify_batch(provider, msgs)
    except Exception:  # noqa: BLE001
        out = []
        for msg in msgs:
            try:
                out.append(classify(provider, msg))
            except Exception as exc:  # noqa: BLE001
                out.append((MailClassification(kind="not_evidence"), f"unclassified: {str(exc)[:200]}"))
        return out


def execute_sync(sync_id: uuid.UUID) -> None:
    """背景执行。已处理的信逐封 commit（失败后再按一次会跳过它们）；失败的同步不推进时间窗口。"""
    with get_sessionmaker()() as db:
        sync = db.get(EmailSync, sync_id)
        if sync is None:
            return
        try:
            provider = provider_for_task(db, "email_classify")
            client, account = gmail_client(db)
            new, before = _list_new(db, client, sync)
            max_new = getattr(client, "max_new", MAX_NEW)  # 经 Claude CLI 读信较慢，一次少读一些
            capped = len(new) > max_new
            sync.truncated = capped or before is not None
            new = new[:max_new]
            sync.fetched = len(new)
            db.commit()
            last = None
            for i in range(0, len(new), BATCH):
                msgs = [client.get(mid) for mid in new[i : i + BATCH]]
                for msg, (cls, reason) in zip(msgs, _classify_all(provider, msgs), strict=True):
                    row = EmailMessage(
                        id=msg.id,
                        account=account,
                        rfc822_id=msg.rfc822_id,
                        thread_id=msg.thread_id,
                        view_url=msg.view_url,
                        sync_id=sync.id,
                        received_at=msg.received_at,
                        from_addr=msg.from_addr[:300],
                        subject=msg.subject[:500],
                        excerpt=_excerpt(cls.evidence, msg.text, cls.kind, reason),
                        kind=cls.kind,
                        company=cls.company or None,
                        title=cls.title or None,
                        requisition_id=cls.requisition_id or None,
                        outcome="needs_review",
                    )
                    db.add(row)
                    db.flush()
                    if cls.kind == "not_evidence" and reason:
                        row.reason = reason  # 分类失败：留给用户看，不套规则
                    else:
                        decide_and_apply(db, row, cls, reason)
                    sync.processed += 1
                    last = msg.received_at
                    db.commit()
            # 没读完的话，窗口只推进到读完的地方，下次（往回重叠 3 天）接着读
            sync.window_before = (last if capped and last else None) or before or sync.started_at
            sync.summary = summary_of(db, sync)
            sync.status, sync.finished_at = "completed", datetime.now(UTC)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - 任何错误都写进同步，不停在「进行中」
            db.rollback()
            sync = db.get(EmailSync, sync_id)
            sync.status, sync.finished_at = "failed", datetime.now(UTC)
            sync.error = str(exc) if isinstance(exc, LLMError) else tr("邮件同步失败：{e}", e=str(exc)[:300])
            sync.summary = summary_of(db, sync)  # 失败前已处理的信照样列出来
            db.commit()


def start_sync(sync_id: uuid.UUID) -> None:
    # copy_context：背景执行沿用发起请求时的介面语言
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(execute_sync, sync_id), name=f"email-{sync_id}", daemon=True).start()


def message_out(row: EmailMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_addr": row.from_addr,
        "subject": row.subject,
        "received_at": row.received_at.isoformat(),
        "excerpt": row.excerpt,
        "kind": row.kind,
        "company": row.company,
        "title": row.title,
        "gmail_url": row.gmail_url,
    }


def _job_out(db: Session, job_id: uuid.UUID | str | None) -> dict[str, Any]:
    job = db.get(Job, job_id) if job_id else None
    if job is None:
        return {"job_id": None, "company": None, "title": None, "status": None}
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    return {
        "job_id": str(job.id),
        "company": job.company.display_name,
        "title": job.title,
        "status": app.status if app else None,
    }


def summary_of(db: Session, sync: EmailSync) -> dict[str, Any]:
    rows = db.scalars(
        select(EmailMessage).where(EmailMessage.sync_id == sync.id).order_by(EmailMessage.received_at)
    ).all()
    out: dict[str, Any] = {"created": [], "updated": [], "evidence_only": [], "needs_review": 0, "ignored": 0}
    out["query_version"] = QUERY_VERSION
    for row in rows:
        if row.outcome in ("ignored", "needs_review"):
            out[row.outcome] += 1
            continue
        item = {**_job_out(db, row.job_id), "message": message_out(row)}
        ev = db.scalar(select(ApplicationEvent).where(ApplicationEvent.email_message_id == row.id))
        item["from"], item["to"] = (ev.from_status, ev.to_status) if ev else (None, None)
        if row.outcome in out:
            out[row.outcome].append(item)
    return out


def needs_review(db: Session) -> list[dict[str, Any]]:
    """所有还没处理的「需要确认」（不限这次同步）。"""
    rows = db.scalars(
        select(EmailMessage).where(EmailMessage.outcome == "needs_review").order_by(EmailMessage.received_at)
    ).all()
    out = []
    for r in rows:
        # 候选职位用现在同公司的职位（同步之后可能新建了）；信里没写公司就用当时记下的
        jobs = [j.id for j in candidate_jobs(db, r.company, r.from_addr)] or (r.candidates or [])
        out.append(
            {
                "message": message_out(r),
                "reason": reason_text(r.reason),
                "candidates": [_job_out(db, j) for j in jobs],
                "bulk_create": can_bulk_create(db, r),
            }
        )
    return out


def sync_out(db: Session, sync: EmailSync) -> dict[str, Any]:
    return {
        "id": str(sync.id),
        "status": sync.status,
        "window_after": sync.window_after.isoformat(),
        "window_before": sync.window_before.isoformat() if sync.window_before else None,
        "fetched": sync.fetched,
        "processed": sync.processed,
        "truncated": sync.truncated,
        "error": sync.error,
        "started_at": sync.started_at.isoformat(),
        "finished_at": sync.finished_at.isoformat() if sync.finished_at else None,
        "summary": sync.summary,
        "needs_review": needs_review(db),
    }


def recover_interrupted_syncs() -> None:
    """服务启动时：上次没跑完的同步标成失败；已处理的信保留，再按一次会跳过。"""
    try:
        with get_sessionmaker()() as db:
            for s in db.scalars(select(EmailSync).where(EmailSync.status == "running")):
                s.status, s.finished_at = "failed", datetime.now(UTC)
                s.error = tr("后端重新启动，同步中断了，请再按一次。")
            db.commit()
    except Exception:  # noqa: BLE001  数据库还没启动时不影响服务启动
        pass
