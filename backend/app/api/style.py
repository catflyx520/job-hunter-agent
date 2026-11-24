"""写法规则：列出、手动加、删除 / 恢复、重新整理。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.i18n import tr
from app.llm.base import LLMError
from app.materials.style import StyleError, active_rules, add_rule, learn_style, saved_edits, set_status
from app.models import Material, StyleRule

router = APIRouter(prefix="/api", tags=["style"])
Kind = Literal["cover_letter", "qa"]


class RuleOut(BaseModel):
    id: uuid.UUID
    kind: Kind
    text: str
    origin: Literal["learned", "manual"]
    status: Literal["active", "removed"]
    source_count: int
    updated_at: datetime


class KindStyle(BaseModel):
    rules: list[RuleOut]
    removed: list[RuleOut]
    samples: int
    pending: int


class LearnOut(BaseModel):
    added: list[str]
    dropped: list[str]
    style: KindStyle


class RuleIn(BaseModel):
    kind: Kind
    text: str


class RuleStatus(BaseModel):
    status: Literal["active", "removed"]


class LearnIn(BaseModel):
    kind: Kind


def _style(db: Session, kind: str) -> KindStyle:
    edits = list(db.execute(saved_edits(kind).with_only_columns(Material.id, Material.style_learned_at)))
    live = {i for i, _ in edits}

    def out(r: StyleRule) -> RuleOut:
        return RuleOut(
            id=r.id,
            kind=r.kind,
            text=r.text,
            origin=r.origin,
            status=r.status,
            source_count=sum(1 for i in r.source_material_ids if i in live),
            updated_at=r.updated_at,
        )

    active = db.scalars(active_rules(kind))
    removed = db.scalars(
        select(StyleRule)
        .where(StyleRule.kind == kind, StyleRule.status == "removed")
        .order_by(StyleRule.updated_at.desc(), StyleRule.id)
    )
    return KindStyle(
        rules=[out(r) for r in active],
        removed=[out(r) for r in removed],
        samples=len(edits),
        pending=sum(1 for _, learned in edits if learned is None),
    )


def _rule_out(db: Session, rule: StyleRule) -> RuleOut:
    style = _style(db, rule.kind)
    return next(r for r in style.rules + style.removed if r.id == rule.id)


@router.get("/style-rules")
def list_rules(db: Session = Depends(get_db)) -> dict[str, KindStyle]:
    return {k: _style(db, k) for k in ("cover_letter", "qa")}


@router.post("/style-rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    try:
        rule = add_rule(db, body.kind, body.text)
    except StyleError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _rule_out(db, rule)


@router.patch("/style-rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RuleStatus, db: Session = Depends(get_db)):
    rule = db.get(StyleRule, rule_id)
    if rule is None:
        raise HTTPException(404, tr("找不到这条写法。"))
    try:
        set_status(db, rule, body.status)
    except StyleError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _rule_out(db, rule)


@router.post("/style-rules/learn", response_model=LearnOut)
def learn(body: LearnIn, db: Session = Depends(get_db)):
    try:
        result = learn_style(db, body.kind)
    except StyleError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return LearnOut(added=result.added, dropped=result.dropped, style=_style(db, body.kind))
