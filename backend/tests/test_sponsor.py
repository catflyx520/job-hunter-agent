"""签证资料管线与雇主比对（合成的官方格式档案，不含真实资料）。"""

import csv

import pytest
from openpyxl import Workbook

from app.models import Company, EmployerAlias
from app.sponsor.lookup import compute_status, refresh_company
from app.sponsor.pipeline import PipelineError, aggregate, identify, import_summary, write_summary

LCA_HEADERS = [
    "CASE_NUMBER",
    "CASE_STATUS",
    "VISA_CLASS",
    "EMPLOYER_NAME",
    "EMPLOYER_CITY",
    "EMPLOYER_STATE",
    "JOB_TITLE",
]


def _xlsx(path, headers, rows, preamble=False):
    wb = Workbook()
    ws = wb.active
    if preamble:
        ws.append(["Disclosure data, synthetic"])  # 有些年份表头前有说明列
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(path)


@pytest.fixture
def raw_dir(tmp_path):
    _xlsx(
        tmp_path / "LCA_Disclosure_Data_FY2025_Q3.xlsx",
        LCA_HEADERS,
        [
            ["I-1", "Certified", "H-1B", "Example Robotics, Inc.", "LOS ANGELES", "CA", "Software Engineer"],
            ["I-2", "Denied", "H-1B", "Example Robotics Inc", "LOS ANGELES", "CA", "Data Engineer"],
        ],
    )
    _xlsx(
        tmp_path / "LCA_Disclosure_Data_FY2025_Q4.xlsx",
        LCA_HEADERS,
        [
            # I-1 在 Q4 再次出现（季度档重叠）→ 只算一次，状态以较新的为准
            [
                "I-1",
                "Certified - Withdrawn",
                "H-1B",
                "Example Robotics, Inc.",
                "LOS ANGELES",
                "CA",
                "Software Engineer",
            ],
            ["I-3", "Certified", "E-3 Australian", "Example Robotics, Inc.", "LOS ANGELES", "CA", "Engineer"],
            ["I-4", "Certified", "H-1B", "Exampel Robotix LLC", "AUSTIN", "TX", "Engineer"],
        ],
        preamble=True,
    )
    _xlsx(
        tmp_path / "PERM_Disclosure_Data_FY2025_Q4.xlsx",
        ["CASE_NUMBER", "CASE_STATUS", "EMP_BUSINESS_NAME", "EMP_CITY", "EMP_STATE", "JOB_OPP_JOB_TITLE"],
        [["P-1", "Certified", "EXAMPLE ROBOTICS INC", "Los Angeles", "CA", "Senior Engineer"]],
    )
    with (tmp_path / "h1b_datahubexport-2023.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Fiscal Year", "Employer (Petitioner) Name", "Initial Approval", "Initial Denial",
                    "Continuing Approval", "Continuing Denial", "Petitioner City", "Petitioner State"])  # fmt: skip
        w.writerow(["2023", "EXAMPLE ROBOTICS INC", "3", "1", "2", "0", "LOS ANGELES", "CA"])
    (tmp_path / "notes.txt").write_text("ignored")
    return tmp_path


def _files(raw_dir):
    return [sf for p in sorted(raw_dir.iterdir()) if (sf := identify(p))]


def test_aggregate_dedupes_and_filters(raw_dir):
    files = _files(raw_dir)
    assert {(f.program, f.fiscal_year, f.quarter) for f in files} == {
        ("lca", 2025, 3), ("lca", 2025, 4), ("perm", 2025, 4), ("uscis_h1b", 2023, None)
    }  # fmt: skip
    employers, rows = aggregate(files, log=lambda *_: None)
    er = employers["example robotics"]
    assert er.filed[("lca", 2025)] == 2  # I-1 去重、I-3 不是 H-1B
    assert er.approved[("lca", 2025)] == 1  # I-1 最新状态 Certified - Withdrawn 仍算 certified
    assert er.denied[("lca", 2025)] == 1
    assert er.approved[("perm", 2025)] == 1
    assert er.approved[("uscis_h1b", 2023)] == 5 and er.denied[("uscis_h1b", 2023)] == 1
    assert "exampel robotix" in employers  # 拼错的不同名称不合并
    assert rows["LCA_Disclosure_Data_FY2025_Q4.xlsx"] == 3


def test_empty_file_is_an_error_not_no_match(tmp_path):
    _xlsx(tmp_path / "LCA_Disclosure_Data_FY2025_Q1.xlsx", LCA_HEADERS, [])
    with pytest.raises(PipelineError, match="读不到"):
        aggregate(_files(tmp_path), log=lambda *_: None)


def test_import_and_four_statuses(raw_dir, tmp_path, db_session):
    db = db_session
    company = Company(display_name="Example Robotics", normalized_name="example robotics")
    other = Company(display_name="Exampel Robotix Corp", normalized_name="exampel robotix corp")
    agency = Company(display_name="Talent Staffing", normalized_name="talent staffing", is_staffing_agency=True)
    db.add_all([company, other, agency])
    db.flush()

    # 未导入资料 → 未查
    assert compute_status(db, company).status == "not_checked"

    files = _files(raw_dir)
    employers, rows = aggregate(files, log=lambda *_: None)
    summary = write_summary(employers, files, rows, tmp_path / "summary.jsonl.gz")
    result = import_summary(db, summary, log=lambda *_: None)
    assert result["datasets"] == 4 and result["employers"] == 2

    # 名称完全相同 → 自动确认 → 有记录
    st = refresh_company(db, company)
    assert st.status == "records_found"
    assert st.h1b_years == [2023, 2025] and st.perm_years == [2025]
    assert st.summary["entities"][0]["method"] == "exact"
    assert set(st.coverage["programs"]) == {"lca", "perm", "uscis_h1b"}

    # 只有相似名称 → 建议，等确认 → 雇主不明
    st2 = refresh_company(db, other)
    assert st2.status == "employer_unknown" and st2.summary["pending"]
    alias = db.query(EmployerAlias).filter_by(company_id=other.id).one()
    assert alias.status == "suggested" and alias.method == "fuzzy"
    alias.status = "confirmed"
    db.flush()
    assert compute_status(db, other).status == "records_found"

    # 猎头 → 雇主不明，不计记录
    assert refresh_company(db, agency).status == "employer_unknown"

    # 重复导入同一份汇总档不会让数字加倍
    import_summary(db, summary, log=lambda *_: None)
    again = compute_status(db, company)
    assert again.summary["programs"]["lca"][0]["filed"] == 2


def test_no_match_mentions_brand_vs_legal_entity(raw_dir, tmp_path, db_session):
    db = db_session
    files = _files(raw_dir)
    employers, rows = aggregate(files, log=lambda *_: None)
    import_summary(db, write_summary(employers, files, rows, tmp_path / "s.jsonl.gz"), log=lambda *_: None)
    c = Company(display_name="Totally Different Co", normalized_name="totally different")
    db.add(c)
    db.flush()
    st = refresh_company(db, c)
    assert st.status == "no_match_in_scope"
    assert "法律实体" in st.summary["reason"]
