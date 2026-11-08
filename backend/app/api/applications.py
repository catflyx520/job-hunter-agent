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
from app.models import Application, ApplicationEvent, Job, Material, Resume

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
        raise HTTPException(404, "找不到这个职位")
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
            raise HTTPException(422, "找不到这份 cover letter")
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
        raise HTTPException(409, "这个职位没有被删除，不需要还原。")
    change_status(db, app, app.previous_status or "saved", "还原")
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
