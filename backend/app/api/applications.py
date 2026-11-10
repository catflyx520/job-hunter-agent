"""F5 投递追踪：状态由用户标记；app 不自动投递、不编造提交时间。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.i18n import tr
from app.jobs.exclusion import blacklist_reasons
from app.models import Application, ApplicationEvent, Job, Material, Preferences, Resume
from app.schemas.profile import Blacklist, JobPreferences

router = APIRouter(prefix="/api", tags=["applications"])

Status = Literal["saved", "applied", "interviewing", "offer", "rejected", "ghosted", "dismissed"]
# 这些状态代表「已经投出去了」：第一次进入时记下投递时间（就是用户标记的时间）
SUBMITTED = {"applied", "interviewing", "offer", "rejected", "ghosted"}


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: str | None
    to_status: str
    note: str | None
    at: datetime


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    status: Status
    previous_status: str | None
    applied_at: datetime | None
    resume_id: uuid.UUID | None
    cover_letter_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    events: list[EventOut] = Field(default_factory=list)


class ApplicationIn(BaseModel):
    status: Status
    note: str | None = Field(None, max_length=2000)  # 这次变更的备注（写进历史）
    notes: str | None = Field(None, max_length=10_000)  # 整体备注（覆盖）
    cover_letter_id: uuid.UUID | None = None


def _job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, tr("找不到这个职位"))
    return job


def _app(db: Session, job_id: uuid.UUID) -> Application | None:
    return db.scalar(select(Application).where(Application.job_id == job_id))


def change_status(db: Session, app: Application, to: str, note: str | None = None) -> None:
    """改状态并新增一笔历史。状态没变就不记。"""
    if app.status == to:
        return
    db.add(ApplicationEvent(application_id=app.id, from_status=app.status, to_status=to, note=note or None))
    if to == "dismissed":
        app.previous_status = app.status
    if to in SUBMITTED and app.applied_at is None:
        app.applied_at = datetime.now(UTC)
        app.resume_id = app.resume_id or db.scalar(select(Resume.id).where(Resume.is_active.is_(True)))
    app.status = to


@router.get("/jobs/{job_id}/application", response_model=ApplicationOut | None)
def get_application(job_id: uuid.UUID, db: Session = Depends(get_db)):
    _job(db, job_id)
    return _app(db, job_id)


@router.put("/jobs/{job_id}/application", response_model=ApplicationOut)
def set_application(job_id: uuid.UUID, body: ApplicationIn, db: Session = Depends(get_db)):
    _job(db, job_id)
    if body.cover_letter_id is not None:
        m = db.get(Material, body.cover_letter_id)
        if m is None or m.kind != "cover_letter":
            raise HTTPException(422, tr("找不到这份 cover letter"))
    app = _app(db, job_id)
    if app is None:
        app = Application(job_id=job_id, status=body.status)
        db.add(app)
        db.flush()
        db.add(ApplicationEvent(application_id=app.id, from_status=None, to_status=body.status, note=body.note))
        if body.status in SUBMITTED:
            app.applied_at = datetime.now(UTC)
            app.resume_id = db.scalar(select(Resume.id).where(Resume.is_active.is_(True)))
    else:
        change_status(db, app, body.status, body.note)
    if body.notes is not None:
        app.notes = body.notes.strip() or None
    if body.cover_letter_id is not None:
        app.cover_letter_id = body.cover_letter_id
    db.flush()
    db.refresh(app)
    return app


@router.post("/jobs/{job_id}/application/restore", response_model=ApplicationOut)
def restore_application(job_id: uuid.UUID, db: Session = Depends(get_db)):
    app = _app(db, job_id)
    if app is None or app.status != "dismissed":
        raise HTTPException(409, tr("这个职位没有被删除，不需要还原。"))
    change_status(db, app, app.previous_status or "saved", tr("还原"))
    app.previous_status = None
    db.flush()
    db.refresh(app)
    return app


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(status: Status | None = None, db: Session = Depends(get_db)):
    q = select(Application).order_by(Application.updated_at.desc())
    if status:
        q = q.where(Application.status == status)
    return db.scalars(q.limit(1000)).all()


# ---------- 黑名单 ----------


class BlacklistIn(BaseModel):
    kind: Literal["company", "title"]
    value: str = Field(min_length=1, max_length=200)


class BlacklistOut(BaseModel):
    blacklist: Blacklist
    dismissed: int  # 这次移到「已删除」的职位数
    kept_submitted: int  # 符合但已投递过、为了保留投递记录没有删除的职位数


@router.post("/blacklist", response_model=BlacklistOut)
def add_to_blacklist(body: BlacklistIn, db: Session = Depends(get_db)):
    """加进黑名单（存在求职需求里，版本 +1），并把已存的相符职位移到「已删除」（可还原）。
    已经投递过的不删，免得投递记录从统计里消失。之后的搜索会把相符的职位排除。"""
    row = db.get(Preferences, 1)
    prefs = JobPreferences.model_validate(row.data) if row else JobPreferences()
    value = " ".join(body.value.split())
    items = prefs.blacklist.companies if body.kind == "company" else prefs.blacklist.titles
    if value.lower() not in {x.lower() for x in items}:
        items.append(value)
    prefs = JobPreferences.model_validate(prefs.model_dump())
    if row is None:
        db.add(Preferences(id=1, data=prefs.model_dump(), version=1))
    elif row.data != prefs.model_dump():
        row.data = prefs.model_dump()
        row.version += 1

    only = Blacklist(
        companies=[value] if body.kind == "company" else [], titles=[value] if body.kind == "title" else []
    )
    dismissed = kept = 0
    for job in db.scalars(select(Job)):
        if not blacklist_reasons(job, only):
            continue
        app = _app(db, job.id)
        if app is not None and app.status in SUBMITTED:
            kept += 1
            continue
        if app is None:
            app = Application(job_id=job.id, status="dismissed", previous_status="saved")
            db.add(app)
            db.flush()
            db.add(
                ApplicationEvent(application_id=app.id, from_status=None, to_status="dismissed", note=tr("加入黑名单"))
            )
            dismissed += 1
        elif app.status != "dismissed":
            change_status(db, app, "dismissed", tr("加入黑名单"))
            dismissed += 1
    db.flush()
    return BlacklistOut(blacklist=prefs.blacklist, dismissed=dismissed, kept_submitted=kept)
