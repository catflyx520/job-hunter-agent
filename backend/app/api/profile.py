"""F2 求职需求与个人事实库。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Fact, Preferences
from app.schemas.profile import (
    FACT_TEMPLATES,
    FactIn,
    FactOut,
    FactTemplate,
    FactUpdate,
    JobPreferences,
    PreferencesOut,
)

router = APIRouter(prefix="/api", tags=["profile"])


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(db: Session = Depends(get_db)):
    row = db.get(Preferences, 1)
    if row is None:
        return PreferencesOut(data=JobPreferences(), version=0, updated_at=None)
    return PreferencesOut(data=JobPreferences.model_validate(row.data), version=row.version, updated_at=row.updated_at)


@router.put("/preferences", response_model=PreferencesOut)
def put_preferences(body: JobPreferences, db: Session = Depends(get_db)):
    row = db.get(Preferences, 1)
    if row is None:
        row = Preferences(id=1, data=body.model_dump(), version=1)
        db.add(row)
    elif row.data != body.model_dump():
        row.data = body.model_dump()
        row.version += 1
    db.flush()
    db.refresh(row)
    return PreferencesOut(data=JobPreferences.model_validate(row.data), version=row.version, updated_at=row.updated_at)


# ---------- 个人事实库 ----------


def _get_fact(db: Session, fact_id: uuid.UUID) -> Fact:
    fact = db.get(Fact, fact_id)
    if fact is None:
        raise HTTPException(404, "找不到这条事实")
    return fact


@router.get("/facts/templates", response_model=list[FactTemplate])
def fact_templates(db: Session = Depends(get_db)):
    """常见申请问题；已经建立的 key 不再列出。"""
    existing = set(db.scalars(select(Fact.key)))
    return [t for t in FACT_TEMPLATES if t.key not in existing]


@router.get("/facts", response_model=list[FactOut])
def list_facts(db: Session = Depends(get_db)):
    return db.scalars(select(Fact).order_by(Fact.created_at)).all()


@router.post("/facts", response_model=FactOut, status_code=201)
def create_fact(body: FactIn, db: Session = Depends(get_db)):
    if db.scalar(select(Fact).where(Fact.key == body.key)) is not None:
        raise HTTPException(409, f"key「{body.key}」已存在")
    if body.confirm and not body.value.strip():
        raise HTTPException(422, "空白的答案不能标记为已确认")
    fact = Fact(
        key=body.key,
        question=body.question,
        value=body.value,
        value_type=body.value_type,
        source=body.source,
        confirmed_at=datetime.now(UTC) if body.confirm else None,
    )
    db.add(fact)
    db.flush()
    db.refresh(fact)
    return fact


@router.patch("/facts/{fact_id}", response_model=FactOut)
def update_fact(fact_id: uuid.UUID, body: FactUpdate, db: Session = Depends(get_db)):
    fact = _get_fact(db, fact_id)
    data = body.model_dump(exclude_unset=True)
    changed_value = "value" in data and data["value"] != fact.value
    for field in ("question", "value", "value_type"):
        if field in data and data[field] is not None:
            setattr(fact, field, data[field])
    if body.confirm is True:
        if not fact.value.strip():
            raise HTTPException(422, "空白的答案不能标记为已确认")
        fact.confirmed_at = datetime.now(UTC)
        fact.source = "user_confirmed" if fact.source == "resume_derived" else fact.source
    elif body.confirm is False or (changed_value and body.confirm is None):
        # 改了答案但没有再次确认 → 视为未确认，生成内容时不会使用
        fact.confirmed_at = None
    db.flush()
    db.refresh(fact)
    return fact


@router.delete("/facts/{fact_id}", status_code=204)
def delete_fact(fact_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get_fact(db, fact_id))
