"""Cover letter / 申请问答：取得 JD → 跑 materials_graph → 保存草稿与附图。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.fetch import fetch_page
from app.core.i18n import tr
from app.graphs.materials import build_graph
from app.llm.base import ImageInput, LLMError, NotSupported
from app.llm.registry import provider_for_task
from app.materials.images import ValidImage, save_images
from app.models import Job, Material, MaterialImage, Resume


class MaterialError(ValueError):
    pass


@dataclass
class MaterialRequest:
    kind: str
    job_id: uuid.UUID | None = None
    url: str | None = None
    jd_text: str | None = None
    question: str | None = None
    requirements: str | None = None
    language: str = "en"
    images: list[ValidImage] | None = None


def resolve_jd(db: Session, req: MaterialRequest) -> tuple[str, str | None, Job | None]:
    """JD 优先顺序（SPEC F4）：已存的完整 JD → 读取公开网址 → 贴上的 JD。读不到就请用户贴，不拿摘要充当完整 JD。"""
    job = db.get(Job, req.job_id) if req.job_id else None
    if req.job_id and job is None:
        raise MaterialError(tr("找不到这个职位。"))
    if job and job.jd_text:
        return "stored", None, job
    if req.jd_text and req.jd_text.strip():
        return "pasted", req.jd_text.strip(), job
    if req.url:
        return "url", fetch_page(req.url).text, job  # FetchError 由 API 转成「请贴 JD」
    return "none", None, job


def create_material(db: Session, req: MaterialRequest) -> Material:
    if req.kind == "qa" and not (req.question or "").strip() and not req.images:
        raise MaterialError(tr("请输入问题，或附上问题截图。"))
    resume = db.scalar(select(Resume).where(Resume.is_active.is_(True)))
    if resume is None:
        raise MaterialError(tr("请先上传并设定一份使用中的履历。"))
    jd_source, jd_text, job = resolve_jd(db, req)
    if req.kind == "cover_letter" and jd_source == "none":
        raise MaterialError(tr("Cover letter 需要 JD：请选一个已存的职位、贴网址或贴上 JD。"))

    provider = provider_for_task(db, "cover_letter" if req.kind == "cover_letter" else "qa")
    if req.images and not provider.capabilities().vision:
        raise NotSupported(tr("目前指定的模型不支援图片。请改贴问题文字，或在设置页为「申请问答」指定支援图片的模型。"))

    full_jd = job.jd_text if jd_source == "stored" and job else jd_text
    m = Material(
        id=uuid.uuid4(),
        job_id=job.id if job else None,
        kind=req.kind,
        question=(req.question or "").strip() or None,
        requirements=(req.requirements or "").strip() or None,
        jd_source=jd_source,
        jd_text=jd_text if jd_source in ("pasted", "url") else None,
        jd_sha256=hashlib.sha256(full_jd.encode()).hexdigest() if full_jd else None,
        resume_id=resume.id,
        status="running",
        provider_kind=provider.kind,
        model=provider.model,
    )
    db.add(m)
    db.flush()
    if req.images:
        for pos, rel, img in save_images(get_settings().data_dir, str(m.id), req.images):
            db.add(
                MaterialImage(
                    material_id=m.id,
                    position=pos,
                    file_path=rel,
                    mime=img.mime,
                    size_bytes=len(img.data),
                    width=img.width,
                    height=img.height,
                    sha256=img.sha256,
                )
            )
        db.flush()

    try:
        state = build_graph(provider, db, resume).invoke(
            {
                "kind": req.kind,
                "language": "zh" if req.language == "zh" else "en",
                "jd_text": (full_jd or "")[:20_000],
                "job_title": job.title if job else "",
                "company": job.company.display_name if job else "",
                "question": m.question or "",
                "requirements": m.requirements or "",
                "images": [ImageInput(i.mime, i.data) for i in (req.images or [])],
            }
        )
    except LLMError as exc:
        m.status, m.error = "failed", str(exc)
        db.flush()
        return m
    m.output_text = state["draft"].text
    m.citations = state["citations"]
    m.needs_confirmation = state["needs_confirmation"]
    m.facts_used = state["facts_used"] or None
    m.status = "done"
    _embed_question(db, m)
    db.flush()
    return m


def _embed_question(db: Session, m: Material) -> None:
    """有 embedding 模型时，替问题算向量，供题库检索；没有就略过（题库改用文字比对）。"""
    if m.kind != "qa" or not m.question:
        return
    try:
        m.question_embedding = provider_for_task(db, "embedding").embed([m.question])[0]
    except LLMError:
        m.question_embedding = None


def similar_answers(db: Session, question: str, limit: int = 5) -> list[Material]:
    base = select(Material).where(Material.kind == "qa", Material.status == "done")
    try:
        vec = provider_for_task(db, "embedding").embed([question])[0]
        rows = db.scalars(
            base.where(Material.question_embedding.is_not(None))
            .order_by(Material.question_embedding.cosine_distance(vec))
            .limit(limit)
        ).all()
        if rows:
            return list(rows)
    except LLMError:
        pass
    words = [w for w in question.split() if len(w) > 3][:6]
    if not words:
        return []
    cond = None
    for w in words:
        c = Material.question.ilike(f"%{w}%")
        cond = c if cond is None else cond | c
    return list(db.scalars(base.where(cond).order_by(Material.created_at.desc()).limit(limit)))
