"""签证资料管线（SPEC F3b）：读取官方原始档 → 汇总 → 导入 Postgres。

支援的档案（档名决定类型与财年，与官方档名相同）：
- DOL LCA：  LCA_Disclosure_Data_FY2025_Q4.xlsx   → program=lca（只计 VISA_CLASS = H-1B，按 CASE_NUMBER 去重）
- DOL PERM： PERM_Disclosure_Data_FY2025_Q4.xlsx  → program=perm（按 CASE_NUMBER 去重）
- USCIS：    h1b_datahubexport-2023.csv           → program=uscis_h1b（Initial / Continuing 批准与拒绝）

只保留雇主层级的汇总数字与职称统计，不保存任何个人资料栏位。
"""

from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import io
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.jobs.normalize import normalize_company
from app.models import SponsorDataset, SponsorEmployer, SponsorStat

DOL_FILE = re.compile(r"^(LCA|PERM)_Disclosure_Data_FY(\d{4})(?:_Q([1-4]))?\.xlsx$", re.I)
USCIS_FILE = re.compile(r"^h1b_datahubexport-(\d{4})\.csv$", re.I)

DOL_BASE = "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
USCIS_BASE = "https://www.uscis.gov/sites/default/files/document/data/"

# 不同年份的栏位名称不一样，统一成同一组
COLUMN_ALIASES = {
    "EMP_BUSINESS_NAME": "EMPLOYER_NAME",
    "EMP_CITY": "EMPLOYER_CITY",
    "EMP_STATE": "EMPLOYER_STATE",
    "JOB_OPP_JOB_TITLE": "JOB_TITLE",
    "JOB_TITLE_SUBGROUP": "JOB_TITLE",
    "EMPLOYER (PETITIONER) NAME": "EMPLOYER",
    "PETITIONER CITY": "CITY",
    "PETITIONER STATE": "STATE",
}


class PipelineError(ValueError):
    pass


@dataclass
class SourceFile:
    path: Path
    program: str
    fiscal_year: int
    quarter: int | None

    @property
    def source_url(self) -> str:
        base = USCIS_BASE if self.program == "uscis_h1b" else DOL_BASE
        return base + self.path.name


def identify(path: Path) -> SourceFile | None:
    if m := DOL_FILE.match(path.name):
        return SourceFile(path, "lca" if m[1].upper() == "LCA" else "perm", int(m[2]), int(m[3]) if m[3] else None)
    if m := USCIS_FILE.match(path.name):
        return SourceFile(path, "uscis_h1b", int(m[1]), None)
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _canon(header: str) -> str:
    h = re.sub(r"\s+", " ", str(header or "")).strip().upper()
    return COLUMN_ALIASES.get(h, h)


def iter_xlsx(path: Path) -> Iterator[dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        headers = None
        for row in rows:
            if headers is None:
                cand = [_canon(c) for c in row]
                if "EMPLOYER_NAME" in cand or "CASE_NUMBER" in cand:
                    headers = cand
                continue
            yield {h: ("" if v is None else str(v)) for h, v in zip(headers, row, strict=False) if h}
    finally:
        wb.close()


def iter_csv(path: Path) -> Iterator[dict[str, str]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    if "\t" in text.splitlines()[0] and "," not in text.splitlines()[0]:
        reader = csv.reader(io.StringIO(text), delimiter="\t")
    else:
        reader = csv.reader(io.StringIO(text))
    headers = [_canon(h) for h in next(reader)]
    for row in reader:
        yield dict(zip(headers, row, strict=False))


def _int(v: str) -> int:
    v = (v or "").replace(",", "").strip()
    try:
        return int(float(v)) if v else 0
    except ValueError:
        return 0


@dataclass
class Agg:
    names: collections.Counter = field(default_factory=collections.Counter)
    cities: collections.Counter = field(default_factory=collections.Counter)
    # (program, fy) -> counters
    filed: collections.Counter = field(default_factory=collections.Counter)
    approved: collections.Counter = field(default_factory=collections.Counter)
    denied: collections.Counter = field(default_factory=collections.Counter)
    titles: dict = field(default_factory=lambda: collections.defaultdict(collections.Counter))
    datasets: dict = field(default_factory=lambda: collections.defaultdict(set))


def aggregate(files: list[SourceFile], log=print, progress=None) -> tuple[dict[str, Agg], dict[str, int]]:
    """回传 {employer_norm: Agg} 与 {档名: 读到的雇主列数}。任何档案读到 0 列就报错（不当成「查无」）。"""
    employers: dict[str, Agg] = collections.defaultdict(Agg)
    rows_read: dict[str, int] = {}
    # DOL 资料按 CASE_NUMBER 去重：同一财年后面季度的档案覆盖前面的
    files = sorted(files, key=lambda f: (f.program, f.fiscal_year, f.quarter or 0))
    # (program, fy) -> {case_number: (row, 档名)}；季度档会重叠，后面的覆盖前面的
    dol_cases: dict[tuple[str, int], dict[str, tuple[dict[str, str], str]]] = collections.defaultdict(dict)
    for i, sf in enumerate(files):
        if progress:
            progress(stage="reading", file=sf.path.name, files_done=i, files_total=len(files))
        n = 0
        if sf.program == "uscis_h1b":
            for r in iter_csv(sf.path):
                name = r.get("EMPLOYER", "").strip()
                if not name:
                    continue
                n += 1
                fy = _int(r.get("FISCAL YEAR", "")) or sf.fiscal_year
                appr = _int(r.get("INITIAL APPROVAL", "")) + _int(r.get("CONTINUING APPROVAL", ""))
                den = _int(r.get("INITIAL DENIAL", "")) + _int(r.get("CONTINUING DENIAL", ""))
                norm = normalize_company(name)
                if not norm:
                    continue
                a = employers[norm]
                a.names[name] += 1
                if r.get("CITY"):
                    a.cities[(r.get("CITY", "").title(), r.get("STATE", "").upper())] += 1
                key = ("uscis_h1b", fy)
                a.approved[key] += appr
                a.denied[key] += den
                a.filed[key] += appr + den
                a.datasets[key].add(sf.path.name)
        else:
            for r in iter_xlsx(sf.path):
                name = r.get("EMPLOYER_NAME", "").strip()
                if not name:
                    continue
                n += 1
                if sf.program == "lca" and r.get("VISA_CLASS", "H-1B").strip().upper() != "H-1B":
                    continue
                dol_cases[(sf.program, sf.fiscal_year)][r.get("CASE_NUMBER") or f"{sf.path.name}#{n}"] = (
                    r,
                    sf.path.name,
                )
        if n == 0:
            raise PipelineError(
                tr(
                    "{name} 读不到任何雇主资料，可能是档案损坏或格式改变；已停止，不会把它当成「查无」。",
                    name=sf.path.name,
                )
            )
        rows_read[sf.path.name] = n
        log(tr("{name}: 读取 {n} 列", name=sf.path.name, n=n))

    for key, cases in dol_cases.items():
        for r, fname in cases.values():
            name = r["EMPLOYER_NAME"].strip()
            norm = normalize_company(name)
            if not norm:
                continue
            a = employers[norm]
            a.names[name] += 1
            if r.get("EMPLOYER_CITY"):
                a.cities[(r["EMPLOYER_CITY"].title(), r.get("EMPLOYER_STATE", "").upper())] += 1
            status = r.get("CASE_STATUS", "").strip().lower()
            a.filed[key] += 1
            if status.startswith("certified"):
                a.approved[key] += 1
            elif status == "denied":
                a.denied[key] += 1
            if r.get("JOB_TITLE"):
                a.titles[key][r["JOB_TITLE"].strip().title()] += 1
            a.datasets[key].add(fname)
    return employers, rows_read


def write_summary(employers: dict[str, Agg], files: list[SourceFile], rows_read: dict[str, int], out: Path) -> Path:
    """输出可发布的汇总档（jsonl.gz）：第一行是 manifest，其余每行一个雇主。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        manifest = {
            "datasets": [
                {
                    "file": sf.path.name,
                    "program": sf.program,
                    "fiscal_year": sf.fiscal_year,
                    "quarter": sf.quarter,
                    "source_url": sf.source_url,
                    "sha256": sha256_file(sf.path),
                    "row_count": rows_read[sf.path.name],
                }
                for sf in files
            ]
        }
        manifest["employer_count"] = len(employers)
        f.write(json.dumps({"manifest": manifest}) + "\n")
        for norm, a in sorted(employers.items()):
            city = a.cities.most_common(1)[0][0] if a.cities else (None, None)
            stats = [
                {
                    "program": p,
                    "fiscal_year": fy,
                    "filed": a.filed[(p, fy)],
                    "certified_or_approved": a.approved[(p, fy)],
                    "denied": a.denied[(p, fy)],
                    "top_titles": [{"title": t, "count": c} for t, c in a.titles[(p, fy)].most_common(5)] or None,
                    "files": sorted(a.datasets[(p, fy)]),
                }
                for (p, fy) in sorted(a.filed)
            ]
            row = {
                "employer_norm": norm,
                "name_variants": [n for n, _ in a.names.most_common(20)],
                "city": city[0],
                "state": city[1],
                "stats": stats,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out


def import_summary(db: Session, summary: Path, log=print, progress=None) -> dict[str, int]:
    """把汇总档导入数据库。同一个资料档（sha256）重复导入时先删除旧数字再写入。"""
    with gzip.open(summary, "rt", encoding="utf-8") as f:
        manifest = json.loads(f.readline())["manifest"]
        file_to_id: dict[str, int] = {}
        for d in manifest["datasets"]:
            if d["row_count"] <= 0:
                raise PipelineError(tr("{v} 的列数为 0，拒绝导入。", v=d["file"]))
            existing = db.scalar(select(SponsorDataset).where(SponsorDataset.sha256 == d["sha256"]))
            if existing is None:
                existing = SponsorDataset(
                    program=d["program"],
                    fiscal_year=d["fiscal_year"],
                    quarter=d["quarter"],
                    source_url=d["source_url"],
                    sha256=d["sha256"],
                    row_count=d["row_count"],
                )
                db.add(existing)
                db.flush()
            file_to_id[d["file"]] = existing.id
        # 同一 program + 财年的旧统计整批替换
        scopes = {(d["program"], d["fiscal_year"]) for d in manifest["datasets"]}
        for program, fy in scopes:
            db.execute(delete(SponsorStat).where(SponsorStat.program == program, SponsorStat.fiscal_year == fy))

        employers = stats = 0
        for line in f:
            row = json.loads(line)
            emp_id = db.scalar(
                insert(SponsorEmployer)
                .values(
                    employer_norm=row["employer_norm"],
                    name_variants=row["name_variants"],
                    city=row["city"],
                    state=row["state"],
                )
                .on_conflict_do_update(
                    index_elements=["employer_norm"],
                    set_={"name_variants": row["name_variants"], "city": row["city"], "state": row["state"]},
                )
                .returning(SponsorEmployer.id)
            )
            employers += 1
            for s in row["stats"]:
                db.add(
                    SponsorStat(
                        employer_id=emp_id,
                        program=s["program"],
                        fiscal_year=s["fiscal_year"],
                        filed=s["filed"],
                        certified_or_approved=s["certified_or_approved"],
                        denied=s["denied"],
                        top_titles=s["top_titles"],
                        dataset_ids=[file_to_id[x] for x in s["files"] if x in file_to_id],
                    )
                )
                stats += 1
            if employers % 5000 == 0:
                db.flush()
                log(tr("已导入 {employers} 个雇主", employers=employers))
                if progress:
                    progress(
                        stage="importing", employers_done=employers, employers_total=manifest.get("employer_count")
                    )
        db.flush()
    return {"employers": employers, "stats": stats, "datasets": len(file_to_id)}
