"""雇主比对与签证状态（SPEC F3b）。

比对顺序：
1. 正规化名称完全相同 → 自动确认（method=exact, confidence 1.00）
2. pg_trgm 相似度 ≥ 0.55 → 列为「建议」，等用户确认（名字相似的不同公司不合并）
3. LLM 从公司官网推测法律实体（entity.py）→ 列为「建议」，附来源链接
只有「已确认」的实体才计入记录。四种状态必须区分：有记录 / 范围内查无 / 未查 / 雇主不明。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, CompanySponsorStatus, EmployerAlias, SponsorDataset, SponsorEmployer, SponsorStat

FUZZY_THRESHOLD = 0.55
NOTES = [
    "历史记录不代表这个职位会提供 sponsorship；JD 写的政策另外显示。",
    "PERM 记录不代表绿卡已核发。",
    "猎头公司的记录不能算成它客户的记录。",
    "LCA 是雇主向劳工部提出的申请，不等于 H-1B 获批；USCIS 数字是批准决定的次数，不是人数。",
]
PROGRAM_LABEL = {"lca": "H-1B LCA（DOL）", "perm": "PERM 绿卡劳工证（DOL）", "uscis_h1b": "H-1B 批准 / 拒绝（USCIS）"}


def coverage(db: Session) -> dict:
    rows = db.execute(
        select(
            SponsorDataset.program, SponsorDataset.fiscal_year, SponsorDataset.quarter, SponsorDataset.source_url
        ).order_by(SponsorDataset.program, SponsorDataset.fiscal_year)
    ).all()
    by_program: dict[str, list[int]] = {}
    for program, fy, _, _ in rows:
        by_program.setdefault(program, [])
        if fy not in by_program[program]:
            by_program[program].append(fy)
    return {
        "programs": {p: sorted(y) for p, y in by_program.items()},
        "sources": sorted({r.source_url for r in rows}),
        "dataset_count": len(rows),
    }


def suggest_aliases(db: Session, company: Company) -> list[EmployerAlias]:
    """建立 exact（自动确认）与 fuzzy（建议）比对；已被用户拒绝的不再建议。"""
    existing = {
        a.sponsor_employer_id: a
        for a in db.scalars(select(EmployerAlias).where(EmployerAlias.company_id == company.id))
    }
    created = []
    exact = db.scalar(select(SponsorEmployer).where(SponsorEmployer.employer_norm == company.normalized_name))
    if exact and exact.id not in existing:
        a = EmployerAlias(
            company_id=company.id,
            sponsor_employer_id=exact.id,
            method="exact",
            confidence=Decimal("1.00"),
            status="confirmed",
            note="正规化后名称完全相同",
        )
        db.add(a)
        created.append(a)
        existing[exact.id] = a
    if not any(a.status == "confirmed" for a in existing.values()):
        rows = db.execute(
            text(
                "SELECT id, similarity(employer_norm, :n) AS s FROM sponsor_employers "
                "WHERE employer_norm % :n ORDER BY s DESC LIMIT 5"
            ),
            {"n": company.normalized_name},
        ).all()
        for emp_id, sim in rows:
            if sim < FUZZY_THRESHOLD or emp_id in existing:
                continue
            a = EmployerAlias(
                company_id=company.id,
                sponsor_employer_id=emp_id,
                method="fuzzy",
                confidence=Decimal(str(round(min(sim, 0.99), 2))),
                status="suggested",
                note="名称相似，需确认是否为同一个法律实体",
            )
            db.add(a)
            created.append(a)
    db.flush()
    return created


def _stats_summary(db: Session, employer_ids: list[int]) -> dict:
    rows = db.execute(
        select(
            SponsorStat.program,
            SponsorStat.fiscal_year,
            func.sum(SponsorStat.filed),
            func.sum(SponsorStat.certified_or_approved),
            func.sum(SponsorStat.denied),
        )
        .where(SponsorStat.employer_id.in_(employer_ids))
        .group_by(SponsorStat.program, SponsorStat.fiscal_year)
        .order_by(SponsorStat.program, SponsorStat.fiscal_year.desc())
    ).all()
    out: dict[str, list[dict]] = {}
    for program, fy, filed, approved, denied in rows:
        out.setdefault(program, []).append(
            {"fiscal_year": fy, "filed": int(filed), "certified_or_approved": int(approved), "denied": int(denied)}
        )
    return out


def compute_status(db: Session, company: Company) -> CompanySponsorStatus:
    cov = coverage(db)
    aliases = list(db.scalars(select(EmployerAlias).where(EmployerAlias.company_id == company.id)))
    confirmed = [a for a in aliases if a.status == "confirmed"]
    pending = [a for a in aliases if a.status == "suggested"]
    summary: dict = {"notes": NOTES, "company": company.display_name, "programs": {}, "entities": [], "pending": []}

    if cov["dataset_count"] == 0:
        status, summary["reason"] = "not_checked", "尚未导入官方签证资料（执行 scripts/sponsor_data/build.py）。"
    elif company.is_staffing_agency:
        status = "employer_unknown"
        summary["reason"] = "职位由猎头 / 人力公司刊登，实际雇主不明；猎头公司的记录不能算成客户的记录。"
    elif confirmed:
        ids = [a.sponsor_employer_id for a in confirmed]
        summary["programs"] = _stats_summary(db, ids)
        summary["entities"] = [
            {
                "name": a.sponsor_employer.name_variants[0]
                if a.sponsor_employer.name_variants
                else a.sponsor_employer.employer_norm,
                "method": a.method,
                "evidence_url": a.evidence_url,
                "note": a.note,
            }
            for a in confirmed
        ]
        has_records = any(
            y["certified_or_approved"] > 0 or y["filed"] > 0 for ys in summary["programs"].values() for y in ys
        )
        status = "records_found" if has_records else "no_match_in_scope"
        if not has_records:
            summary["reason"] = "已确认实体，但在已导入的资料年份里没有记录。"
    elif pending:
        status = "employer_unknown"
        summary["reason"] = "有名称相似的雇主，需要你确认是否为同一个法律实体。"
    else:
        status = "no_match_in_scope"
        summary["reason"] = (
            f"以公司名称「{company.display_name}」在已导入资料中查无记录。品牌名可能与法律实体不同，"
            "可以让 AI 从公司官网推测法律实体后再比对。"
        )
        summary["match_basis"] = "company_name"
    summary["pending"] = [
        {
            "alias_id": str(a.id),
            "name": a.sponsor_employer.name_variants[0]
            if a.sponsor_employer.name_variants
            else a.sponsor_employer.employer_norm,
            "city": a.sponsor_employer.city,
            "state": a.sponsor_employer.state,
            "method": a.method,
            "confidence": float(a.confidence),
            "evidence_url": a.evidence_url,
            "note": a.note,
        }
        for a in pending
    ]

    def years(program: str) -> list[int] | None:
        ys = [y["fiscal_year"] for y in summary["programs"].get(program, []) if y["certified_or_approved"] > 0]
        return sorted(ys) or None

    row = db.get(CompanySponsorStatus, company.id) or CompanySponsorStatus(company_id=company.id)
    row.status = status
    row.h1b_years = sorted(set((years("lca") or []) + (years("uscis_h1b") or []))) or None
    row.perm_years = years("perm")
    row.summary = summary
    row.coverage = cov
    row.computed_at = datetime.now(UTC)
    db.add(row)
    db.flush()
    return row


def refresh_company(db: Session, company: Company) -> CompanySponsorStatus:
    if coverage(db)["dataset_count"]:
        suggest_aliases(db, company)
    return compute_status(db, company)


def recompute_all_statuses(db: Session) -> int:
    n = 0
    for company in db.scalars(select(Company)):
        refresh_company(db, company)
        n += 1
    return n
