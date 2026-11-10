"""检索履历证据：pgvector 向量检索 + Postgres 全文检索，用 RRF（Reciprocal Rank Fusion）合并。

没有 embedding 模型或尚未建立切块时，退回「直接用结构化履历的每一条」，并在结果里说明，
让匹配评分与生成内容仍可引用证据（source_ref）。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.llm.base import LLMError
from app.llm.registry import provider_for_task
from app.models import ExperienceChunk, Resume
from app.rag.chunks import make_chunks
from app.schemas.resume import ParsedResume

RRF_K = 60


@dataclass
class Evidence:
    id: str  # chunk uuid，或 "ref:<source_ref>"（没有切块时）
    source_ref: str
    section: str
    text: str


@dataclass
class Retrieval:
    items: list[Evidence]
    method: str  # hybrid / vector / fulltext / all_chunks / parsed_resume
    note: str | None = None


def _or_query(terms: list[str]) -> str:
    words = {w for t in terms for w in re.findall(r"[a-z0-9][a-z0-9+#.]*", t.lower()) if len(w) > 1}
    return " | ".join(sorted(re.sub(r"[^a-z0-9]", "", w) for w in words if re.sub(r"[^a-z0-9]", "", w)))


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda i: (-scores[i], i))


def retrieve(db: Session, resume: Resume, query: str, keywords: list[str], limit: int = 12) -> Retrieval:
    chunks = {str(c.id): c for c in db.scalars(select(ExperienceChunk).where(ExperienceChunk.resume_id == resume.id))}
    if not chunks:
        parsed = ParsedResume.model_validate(resume.parsed)
        items = [Evidence(f"ref:{c.source_ref}", c.source_ref, c.section, c.text) for c in make_chunks(parsed)]
        return Retrieval(items[:40], "parsed_resume", tr("尚未建立检索切块，直接使用结构化履历的内容。"))

    rankings: list[list[str]] = []
    note = None
    try:
        provider = provider_for_task(db, "embedding")
        qvec = provider.embed([query[:8000]])[0]
        rows = db.execute(
            select(ExperienceChunk.id)
            .where(ExperienceChunk.resume_id == resume.id)
            .order_by(ExperienceChunk.embedding.cosine_distance(qvec))
            .limit(limit * 2)
        ).scalars()
        rankings.append([str(r) for r in rows])
    except LLMError as exc:
        note = tr("向量检索不可用（{exc}），只用全文检索。", exc=exc)

    tsq = _or_query(keywords)
    if tsq:
        rows = db.execute(
            text(
                "SELECT id FROM experience_chunks WHERE resume_id = :rid AND tsv @@ to_tsquery('english', :q) "
                "ORDER BY ts_rank(tsv, to_tsquery('english', :q)) DESC LIMIT :n"
            ),
            {"rid": resume.id, "q": tsq, "n": limit * 2},
        ).scalars()
        rankings.append([str(r) for r in rows])

    if not any(rankings):
        ordered = list(chunks)[:limit]
        method = "all_chunks"
    else:
        ordered = rrf([r for r in rankings if r])[:limit]
        method = "hybrid" if len([r for r in rankings if r]) == 2 else ("vector" if note is None else "fulltext")
    items = [Evidence(i, chunks[i].source_ref, chunks[i].section, chunks[i].text) for i in ordered if i in chunks]
    # 技能与学历切块永远带上，避免遗漏
    for c in chunks.values():
        if c.section in ("skills", "education") and str(c.id) not in ordered:
            items.append(Evidence(str(c.id), c.source_ref, c.section, c.text))
    return Retrieval(items, method, note)


def chunk_uuid(evidence_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(evidence_id)
    except ValueError:
        return None


def evidence_texts(db: Session, ids: list[str], resume_id: uuid.UUID | None) -> dict[str, str]:
    """把证据 ID 换成履历原文：切块 ID 查 experience_chunks；"ref:" ID 从结构化履历找回同一段文字。"""
    out: dict[str, str] = {}
    uuids = [u for i in ids if (u := chunk_uuid(i))]
    if uuids:
        for c in db.scalars(select(ExperienceChunk).where(ExperienceChunk.id.in_(uuids))):
            out[str(c.id)] = c.text
    refs = [i for i in ids if i.startswith("ref:")]
    if refs and resume_id:
        resume = db.get(Resume, resume_id)
        if resume:
            by_ref = {c.source_ref: c.text for c in make_chunks(ParsedResume.model_validate(resume.parsed))}
            for i in refs:
                out[i] = by_ref.get(i[4:], i[4:])
    return out
