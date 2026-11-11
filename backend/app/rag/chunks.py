"""把结构化履历切块并做 embedding（F3 匹配理由与 F4 生成时检索证据用）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import tr
from app.llm.base import LLMError, LLMProvider
from app.models import ExperienceChunk, Resume
from app.schemas.resume import ParsedResume

EMBED_BATCH = 64


@dataclass
class Chunk:
    section: str
    source_ref: str
    text: str


def make_chunks(parsed: ParsedResume) -> list[Chunk]:
    """每个 bullet 一块，前面加上职称与公司，检索时才有上下文；source_ref 指回 parsed 的位置。"""
    chunks: list[Chunk] = []
    if parsed.summary.strip():
        chunks.append(Chunk("summary", "summary", parsed.summary.strip()))
    for i, exp in enumerate(parsed.experience):
        head = " @ ".join(x for x in (exp.title, exp.company) if x)
        for j, bullet in enumerate(exp.bullets):
            if bullet.strip():
                chunks.append(Chunk("experience", f"experience[{i}].bullets[{j}]", f"{head}: {bullet.strip()}"))
    for i, proj in enumerate(parsed.projects):
        head = proj.name + (f" ({', '.join(proj.tech)})" if proj.tech else "")
        if proj.description.strip():
            chunks.append(Chunk("project", f"projects[{i}].description", f"{head}: {proj.description.strip()}"))
        for j, bullet in enumerate(proj.bullets):
            if bullet.strip():
                chunks.append(Chunk("project", f"projects[{i}].bullets[{j}]", f"{head}: {bullet.strip()}"))
    if parsed.skills:
        chunks.append(Chunk("skills", "skills", "Skills: " + ", ".join(parsed.skills)))
    for i, edu in enumerate(parsed.education):
        parts = [edu.degree, edu.field, edu.school, " - ".join(x for x in (edu.start, edu.end) if x)]
        text = ", ".join(p for p in parts if p)
        if edu.details:
            text += ". " + "; ".join(edu.details)
        if text.strip():
            chunks.append(Chunk("education", f"education[{i}]", text))
    return chunks


def rebuild_confirmed(db: Session, provider: LLMProvider) -> int:
    """换了 embedding 模型后，已确认的履历都要重算（不同模型的向量不能互相比较）。回传切块总数。"""
    resumes = db.scalars(select(Resume).where(Resume.parsed_confirmed_at.is_not(None))).all()
    return sum(rebuild_chunks(db, r, provider) for r in resumes)


def rebuild_chunks(db: Session, resume: Resume, provider: LLMProvider) -> int:
    """删掉旧切块，重新切块与计算向量。维度不符时报错，不写入半套资料。"""
    chunks = make_chunks(ParsedResume.model_validate(resume.parsed))
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        vectors += provider.embed([c.text for c in chunks[start : start + EMBED_BATCH]])
    dim = get_settings().embedding_dim
    if vectors and len(vectors[0]) != dim:
        raise LLMError(
            tr(
                "embedding 模型输出 {v} 维，但数据库的向量栏位是 {dim} 维。请换成 {dim} 维的模型（例如 OpenAI 的 text-embedding-3-small）。",
                v=len(vectors[0]),
                dim=dim,
            )
        )
    db.execute(delete(ExperienceChunk).where(ExperienceChunk.resume_id == resume.id))
    for chunk, vec in zip(chunks, vectors, strict=True):
        db.add(
            ExperienceChunk(
                resume_id=resume.id,
                section=chunk.section,
                source_ref=chunk.source_ref,
                text=chunk.text,
                embedding=vec,
                embedding_model=provider.model,
            )
        )
    db.flush()
    return len(chunks)
