"""F2 履历：上传、结构化、确认、切块、版本、评分。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.graphs.resume_review import run_review
from app.llm.base import LLMError
from app.llm.registry import provider_for_task
from app.models import ExperienceChunk, Preferences, Resume, ResumeReview
from app.rag.chunks import rebuild_chunks
from app.resume_review.ats_text import ATS_EXPLAINED
from app.resume_review.extract import ALLOWED_MIMES, UnsupportedFile, extract, sniff_mime
from app.resume_review.structure import structure_resume, unverified_items
from app.schemas.resume import (
    ChunkResult,
    ParsedResume,
    ParsedUpdate,
    ResumeDetail,
    ResumeOut,
    ReviewOut,
    ReviewRequest,
    UploadResult,
)

router = APIRouter(prefix="/api", tags=["resumes"])


def _chunk_count(db: Session, resume_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(ExperienceChunk.resume_id == resume_id)) or 0


def _detail(db: Session, r: Resume) -> ResumeDetail:
    return ResumeDetail.model_validate(
        {
            **{k: getattr(r, k) for k in ResumeDetail.model_fields if hasattr(r, k)},
            "chunk_count": _chunk_count(db, r.id),
        }
    )


def _get(db: Session, resume_id: uuid.UUID) -> Resume:
    r = db.get(Resume, resume_id)
    if r is None:
        raise HTTPException(404, "找不到这份履历")
    return r


def _abs_path(r: Resume) -> Path:
    return get_settings().data_dir / r.file_path


@router.get("/ats-explained")
def ats_explained():
    return ATS_EXPLAINED


@router.post("/resumes", response_model=UploadResult, status_code=201)
def upload_resume(
    file: UploadFile = File(...),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    data = file.file.read(settings.max_resume_bytes + 1)
    if len(data) > settings.max_resume_bytes:
        raise HTTPException(413, f"档案超过 {settings.max_resume_bytes // (1024 * 1024)}MB")
    if not data:
        raise HTTPException(422, "档案是空的")
    filename = Path(file.filename or "resume").name
    try:
        mime = sniff_mime(data, filename)
        extracted = extract(data, mime)
    except UnsupportedFile as exc:
        raise HTTPException(422, str(exc)) from exc

    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Resume).where(Resume.sha256 == sha))
    if existing is not None:
        raise HTTPException(409, f"这份档案已经上传过（「{existing.label}」）。")

    resume_id = uuid.uuid4()
    rel = Path("resumes") / f"{resume_id}{ALLOWED_MIMES[mime]}"
    dest = settings.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    parse_error = None
    parsed = ParsedResume()
    try:
        parsed = structure_resume(provider_for_task(db, "resume_parse"), extracted.text)
    except LLMError as exc:
        parse_error = f"履历结构化失败：{exc} 你可以稍后重试，或在页面上手动填写。"

    has_active = db.scalar(select(func.count()).where(Resume.is_active.is_(True))) or 0
    r = Resume(
        id=resume_id,
        label=label.strip() or Path(filename).stem,
        filename=filename,
        mime=mime,
        file_path=rel.as_posix(),
        sha256=sha,
        raw_text=extracted.text,
        parsed=parsed.model_dump(),
        is_active=not has_active,
    )
    db.add(r)
    db.flush()
    db.refresh(r)
    return UploadResult(
        resume=_detail(db, r),
        parse_error=parse_error,
        unverified_items=unverified_items(parsed, extracted.text) if parse_error is None else [],
    )


@router.get("/resumes", response_model=list[ResumeOut])
def list_resumes(db: Session = Depends(get_db)):
    rows = db.scalars(select(Resume).order_by(Resume.created_at.desc())).all()
    return [_detail(db, r) for r in rows]


@router.get("/resumes/{resume_id}", response_model=ResumeDetail)
def get_resume(resume_id: uuid.UUID, db: Session = Depends(get_db)):
    return _detail(db, _get(db, resume_id))


@router.post("/resumes/{resume_id}/parse", response_model=UploadResult)
def reparse_resume(resume_id: uuid.UUID, db: Session = Depends(get_db)):
    r = _get(db, resume_id)
    try:
        parsed = structure_resume(provider_for_task(db, "resume_parse"), r.raw_text)
    except LLMError as exc:
        raise HTTPException(502, f"履历结构化失败：{exc}") from exc
    r.parsed = parsed.model_dump()
    r.parsed_confirmed_at = None
    db.flush()
    return UploadResult(resume=_detail(db, r), unverified_items=unverified_items(parsed, r.raw_text))


@router.put("/resumes/{resume_id}/parsed", response_model=ResumeDetail)
def update_parsed(resume_id: uuid.UUID, body: ParsedUpdate, db: Session = Depends(get_db)):
    r = _get(db, resume_id)
    r.parsed = body.parsed.model_dump()
    r.parsed_confirmed_at = datetime.now(UTC) if body.confirm else None
    db.flush()
    db.refresh(r)
    return _detail(db, r)


@router.post("/resumes/{resume_id}/chunks", response_model=ChunkResult)
def build_chunks(resume_id: uuid.UUID, db: Session = Depends(get_db)):
    r = _get(db, resume_id)
    if r.parsed_confirmed_at is None:
        raise HTTPException(409, "请先确认结构化履历，再建立检索资料。")
    try:
        provider = provider_for_task(db, "embedding")
        count = rebuild_chunks(db, r, provider)
    except LLMError as exc:
        return ChunkResult(chunk_count=_chunk_count(db, r.id), error=str(exc))
    return ChunkResult(chunk_count=count, embedding_model=provider.model)


@router.post("/resumes/{resume_id}/activate", response_model=ResumeOut)
def activate_resume(resume_id: uuid.UUID, db: Session = Depends(get_db)):
    r = _get(db, resume_id)
    db.execute(update(Resume).where(Resume.is_active.is_(True)).values(is_active=False))
    db.flush()
    r.is_active = True
    db.flush()
    db.refresh(r)
    return _detail(db, r)


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: uuid.UUID, db: Session = Depends(get_db)):
    r = _get(db, resume_id)
    path = _abs_path(r)
    db.delete(r)
    db.flush()
    path.unlink(missing_ok=True)


# ---------- 履历评分 ----------


@router.post("/resumes/{resume_id}/reviews", response_model=ReviewOut, status_code=201)
def create_review(resume_id: uuid.UUID, body: ReviewRequest, db: Session = Depends(get_db)):
    r = _get(db, resume_id)
    target_role = (body.target_role or "").strip() or None
    if target_role is None:
        prefs = db.get(Preferences, 1)
        roles = (prefs.data.get("target_roles") if prefs else None) or []
        target_role = roles[0] if roles else None
    try:
        data = _abs_path(r).read_bytes()
        layout = extract(data, r.mime).layout
    except (OSError, UnsupportedFile) as exc:
        raise HTTPException(409, "找不到或无法读取原始履历档，无法检查版面。") from exc
    try:
        provider = provider_for_task(db, "resume_review")
        out = run_review(provider, r.raw_text, ParsedResume.model_validate(r.parsed), layout, target_role)
    except LLMError as exc:
        raise HTTPException(502, f"履历评分失败：{exc}") from exc
    review = ResumeReview(
        resume_id=r.id,
        target_role=target_role,
        parse_score=out.parse_score,
        content_score=out.content_score,
        keyword_score=out.keyword_score,
        findings=[f.model_dump() for f in out.findings],
        model=f"{provider.kind}:{provider.model}",
    )
    db.add(review)
    db.flush()
    db.refresh(review)
    return review


@router.get("/resumes/{resume_id}/reviews", response_model=list[ReviewOut])
def list_reviews(resume_id: uuid.UUID, db: Session = Depends(get_db)):
    _get(db, resume_id)
    return db.scalars(
        select(ResumeReview).where(ResumeReview.resume_id == resume_id).order_by(ResumeReview.created_at.desc())
    ).all()
