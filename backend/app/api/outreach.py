"""Reach out：找内推人、写内推请求、记录往来。消息由用户自己发送，app 只写草稿与记录。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.applications import _app, mark_referred
from app.api.jobs import _summary
from app.core.db import get_db
from app.core.i18n import tr
from app.core.security import encrypt_secret, last4
from app.jobs.service import IngestError, upsert_company
from app.llm.base import LLMError
from app.models import Company, Contact, Integration, Job, OutreachMessage
from app.outreach import drafts, people
from app.outreach.hunter import HunterError, company_domain, get_hunter, host_of, hunter_row
from app.outreach.people import clean_linkedin_url
from app.schemas.job import JobSummary
from app.schemas.outreach import (
    ContactDetail,
    ContactIn,
    ContactOut,
    ContactPatch,
    ContactSummary,
    EmailLookupIn,
    EmailLookupOut,
    MessageCreated,
    MessageDeleted,
    MessageIn,
    MessageOut,
    MessagePatch,
)

router = APIRouter(prefix="/api", tags=["outreach"])


class HunterIn(BaseModel):
    enabled: bool
    api_key: str | None = Field(None, max_length=500)


class HunterOut(BaseModel):
    enabled: bool
    key_last4: str | None


def _hunter_out(db: Session) -> HunterOut:
    row = hunter_row(db)
    return HunterOut(enabled=bool(row and row.enabled), key_last4=(row.config or {}).get("key_last4") if row else None)


@router.get("/outreach/hunter", response_model=HunterOut)
def get_hunter_settings(db: Session = Depends(get_db)):
    return _hunter_out(db)


@router.put("/outreach/hunter", response_model=HunterOut)
def set_hunter_settings(body: HunterIn, db: Session = Depends(get_db)):
    row = hunter_row(db)
    key = (body.api_key or "").strip()
    if body.enabled and not key and not (row and row.secret_encrypted):
        raise HTTPException(422, tr("请填写 Hunter API key。"))
    if row is None:
        row = Integration(kind="hunter", config={}, enabled=False)
        db.add(row)
    if key:
        row.secret_encrypted = encrypt_secret(key)
        row.config = {**(row.config or {}), "key_last4": last4(key)}
    row.enabled = body.enabled
    db.flush()
    return _hunter_out(db)


@router.post("/outreach/hunter/test")
def test_hunter(db: Session = Depends(get_db)):
    h = get_hunter(db)
    if h is None:
        raise HTTPException(422, tr("请先在设置页启用 Hunter。"))
    try:
        h.check()
    except HunterError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


def _job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, tr("找不到这个职位"))
    return job


class CandidatesIn(BaseModel):
    use_hunter: bool = False


@router.post("/jobs/{job_id}/outreach/candidates", response_model=list[people.Candidate])
def find_candidates(job_id: uuid.UUID, body: CandidatesIn, db: Session = Depends(get_db)):
    """找这家公司可能帮忙内推的人。结果只显示，不存；用户按「加入」才建联系人。"""
    job = _job(db, job_id)
    try:
        return people.find_candidates(db, job, body.use_hunter)
    except LLMError as exc:
        raise HTTPException(422, str(exc)) from exc


# ---------- 联系人 ----------


def _contact(db: Session, contact_id: uuid.UUID) -> Contact:
    c = db.get(Contact, contact_id)
    if c is None:
        raise HTTPException(404, tr("找不到这个联系人"))
    return c


def _linkedin(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    clean = clean_linkedin_url(url)
    if clean is None:
        raise HTTPException(422, tr("请贴 LinkedIn 个人页网址（linkedin.com/in/…）。"))
    return clean


def _contact_out(db: Session, c: Contact) -> ContactOut:
    company = db.get(Company, c.company_id) if c.company_id else None
    return ContactOut.model_validate(c).model_copy(update={"company_name": company.display_name if company else None})


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(body: ContactIn, response: Response, db: Session = Depends(get_db)):
    """同一个 LinkedIn 个人页已经存在就回传原有的联系人（200），不建第二笔。"""
    url = _linkedin(body.linkedin_url)
    if url:
        existing = db.scalar(select(Contact).where(Contact.linkedin_url == url))
        if existing is not None:
            response.status_code = 200
            return _contact_out(db, existing)
    company_id = body.company_id
    if company_id is None and (body.company_name or "").strip():
        try:
            company_id = upsert_company(db, body.company_name or "").id
        except IngestError as exc:
            raise HTTPException(422, str(exc)) from exc
    c = Contact(
        company_id=company_id,
        full_name=body.full_name.strip(),
        title=(body.title or "").strip() or None,
        linkedin_url=url,
        email=body.email,
        email_source=("hunter" if body.found_via == "hunter" else "user") if body.email else None,
        email_confidence=body.email_confidence if body.email else None,
        found_via=body.found_via,
        role_kind=body.role_kind,
        notes=(body.why or "").strip() or None,
    )
    db.add(c)
    db.flush()
    db.refresh(c)
    return _contact_out(db, c)


@router.get("/contacts", response_model=list[ContactSummary])
def list_contacts(
    filter: Literal["all", "waiting", "replied"] = "all",
    company_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    """收件箱左栏：按最近一条消息排序，没有消息的排最后。waiting = 最后一条是你发的；replied = 最后一条是对方的。"""
    last = select(
        OutreachMessage.contact_id,
        OutreachMessage.direction,
        OutreachMessage.sent_at,
        func.row_number()
        .over(partition_by=OutreachMessage.contact_id, order_by=OutreachMessage.sent_at.desc())
        .label("rn"),
        func.count().over(partition_by=OutreachMessage.contact_id).label("n"),
    ).subquery()
    q = (
        select(Contact, Company.display_name, last.c.direction, last.c.sent_at, last.c.n)
        .outerjoin(Company, Company.id == Contact.company_id)
        .outerjoin(last, (last.c.contact_id == Contact.id) & (last.c.rn == 1))
        .order_by(last.c.sent_at.desc().nulls_last(), Contact.created_at.desc())
    )
    if company_id:
        q = q.where(Contact.company_id == company_id)
    if filter == "waiting":
        q = q.where(last.c.direction == "out")
    elif filter == "replied":
        q = q.where(last.c.direction == "in")
    return [
        ContactSummary(
            id=c.id,
            full_name=c.full_name,
            title=c.title,
            company_id=c.company_id,
            company_name=name,
            last_message_at=at,
            last_direction=direction,
            message_count=n or 0,
        )
        for c, name, direction, at, n in db.execute(q).all()
    ]


@router.get("/contacts/{contact_id}", response_model=ContactDetail)
def get_contact(contact_id: uuid.UUID, db: Session = Depends(get_db)):
    c = _contact(db, contact_id)
    job_ids = list(dict.fromkeys(m.job_id for m in c.messages if m.job_id))
    jobs = [JobSummary(**_summary(db, j)) for jid in job_ids if (j := db.get(Job, jid))]
    return ContactDetail(
        **_contact_out(db, c).model_dump(),
        messages=[MessageOut.model_validate(m) for m in c.messages],
        jobs=jobs,
    )


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def patch_contact(contact_id: uuid.UUID, body: ContactPatch, db: Session = Depends(get_db)):
    c = _contact(db, contact_id)
    fields = body.model_fields_set
    if "linkedin_url" in fields:
        url = _linkedin(body.linkedin_url)
        other = db.scalar(select(Contact.id).where(Contact.linkedin_url == url, Contact.id != c.id)) if url else None
        if other:
            raise HTTPException(409, tr("另一个联系人已经用了这个 LinkedIn 网址。"))
        c.linkedin_url = url
    if "email" in fields:
        c.email = body.email
        c.email_source = "user" if body.email else None
        c.email_confidence = None
    if "full_name" in fields and body.full_name:
        c.full_name = body.full_name.strip()
    if "role_kind" in fields and body.role_kind:
        c.role_kind = body.role_kind
    for k in ("title", "notes"):
        if k in fields:
            setattr(c, k, (getattr(body, k) or "").strip() or None)
    db.flush()
    db.refresh(c)
    return _contact_out(db, c)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_contact(db, contact_id))
    db.flush()
    return Response(status_code=204)


@router.post("/contacts/{contact_id}/email-lookup", response_model=EmailLookupOut)
def email_lookup(contact_id: uuid.UUID, body: EmailLookupIn, db: Session = Depends(get_db)):
    """用 Hunter 查邮箱（会用掉一次额度）。给了网域就存回公司网址，下次不用再填。"""
    c = _contact(db, contact_id)
    h = get_hunter(db)
    if h is None:
        raise HTTPException(422, tr("请先在设置页启用 Hunter。"))
    company = db.get(Company, c.company_id) if c.company_id else None
    domain = host_of(body.domain)
    if domain and company is not None:
        company.website = domain
    if not domain:
        job_id = db.scalar(
            select(OutreachMessage.job_id).where(
                OutreachMessage.contact_id == c.id, OutreachMessage.job_id.is_not(None)
            )
        )
        domain = company_domain(company, db.get(Job, job_id) if job_id else None)
    if not domain:
        raise HTTPException(422, tr("请先填写公司网址（例如 example.com）。"))
    first, _, last = c.full_name.strip().partition(" ")
    try:
        found = h.find_email(domain, first, last.strip() or first)
    except HunterError as exc:
        raise HTTPException(422, str(exc)) from exc
    if found:
        c.email, c.email_confidence = found
        c.email_source = "hunter"
    db.flush()
    db.refresh(c)
    return EmailLookupOut(found=bool(found), contact=_contact_out(db, c))


# ---------- 消息 ----------


@router.post("/contacts/{contact_id}/messages", response_model=MessageCreated, status_code=201)
def add_message(contact_id: uuid.UUID, body: MessageIn, db: Session = Depends(get_db)):
    """记录一条你已经发出的消息（「我已发送」）或对方的回复（贴上）。发出的消息挂了职位，就把职位改成已请求内推。"""
    c = _contact(db, contact_id)
    if body.job_id:
        _job(db, body.job_id)
    m = OutreachMessage(
        contact_id=c.id,
        job_id=body.job_id,
        direction=body.direction,
        channel=body.channel,
        style=body.style if body.direction == "out" else None,
        subject=(body.subject or "").strip() or None,
        body=body.body,
        material_meta=body.material_meta if body.direction == "out" else None,
        sent_at=body.sent_at or datetime.now(UTC),
    )
    db.add(m)
    db.flush()
    status = None
    if body.job_id:
        if body.direction == "out":
            status = mark_referred(db, body.job_id, tr("已向 {name} 请求内推", name=c.full_name))
        else:
            app = _app(db, body.job_id)
            status = app.status if app else None
    db.refresh(m)
    return MessageCreated(**MessageOut.model_validate(m).model_dump(), application_status=status)


def _message(db: Session, message_id: uuid.UUID) -> OutreachMessage:
    m = db.get(OutreachMessage, message_id)
    if m is None:
        raise HTTPException(404, tr("找不到这条消息"))
    return m


@router.patch("/messages/{message_id}", response_model=MessageOut)
def patch_message(message_id: uuid.UUID, body: MessagePatch, db: Session = Depends(get_db)):
    m = _message(db, message_id)
    fields = body.model_fields_set
    if "subject" in fields:
        m.subject = (body.subject or "").strip() or None
    for k in ("body", "channel", "sent_at"):
        if k in fields and getattr(body, k) is not None:
            setattr(m, k, getattr(body, k))
    db.flush()
    db.refresh(m)
    return m


@router.delete("/messages/{message_id}", response_model=MessageDeleted)
def delete_message(message_id: uuid.UUID, db: Session = Depends(get_db)):
    """删除不回退职位状态（状态由你控制）；删掉的是这个职位唯一一条发出的消息时提醒一下。"""
    m = _message(db, message_id)
    job_id, was_out = m.job_id, m.direction == "out"
    db.delete(m)
    db.flush()
    warning = None
    if job_id and was_out:
        others = db.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(OutreachMessage.job_id == job_id, OutreachMessage.direction == "out")
        )
        app = _app(db, job_id)
        if not others and app is not None and app.status == "referred":
            warning = tr("职位状态仍是已请求内推，需要的话请手动修改。")
    return MessageDeleted(warning=warning)


# ---------- 草稿 ----------


class DraftsIn(BaseModel):
    contact_id: uuid.UUID
    job_id: uuid.UUID | None = None
    style: Literal["technical", "general"] | None = None
    language: Literal["en", "zh"] = "en"
    follow_up: bool = False


@router.post("/outreach/drafts", response_model=drafts.DraftsOut)
def make_drafts(body: DraftsIn, db: Session = Depends(get_db)):
    """产生草稿给页面编辑，不写进资料库。"""
    c = _contact(db, body.contact_id)
    job = _job(db, body.job_id) if body.job_id else None
    try:
        return drafts.generate_drafts(db, c, job, body.style, body.language, body.follow_up)
    except (drafts.DraftError, LLMError) as exc:
        raise HTTPException(422, str(exc)) from exc
