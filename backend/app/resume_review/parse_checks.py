"""可解析度检查：纯程序规则，不用 LLM。

分数 = 100 减去各项扣分；每一项都写明扣分原因。
"""

from __future__ import annotations

import re

from app.core.i18n import tr
from app.resume_review.extract import LayoutInfo
from app.schemas.resume import Finding

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
LINKEDIN = re.compile(r"linkedin\.com/in/", re.I)

STANDARD_HEADINGS = {
    "experience": re.compile(
        r"^\s*(work |professional |relevant )?(experience|employment( history)?|work history)\s*:?\s*$", re.I | re.M
    ),
    "education": re.compile(r"^\s*education( and training)?\s*:?\s*$", re.I | re.M),
    "skills": re.compile(r"^\s*(technical |core )?skills( (and|&) \w+)?\s*:?\s*$", re.I | re.M),
}

MONTHS_FULL = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTHS_SHORT = "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
DATE_FORMATS: dict[str, re.Pattern[str]] = {
    "Month YYYY": re.compile(rf"\b({MONTHS_FULL})\s+\d{{4}}\b"),
    "Mon YYYY": re.compile(rf"\b({MONTHS_SHORT})\.?\s+\d{{4}}\b"),
    "MM/YYYY": re.compile(r"\b(0?[1-9]|1[0-2])/(19|20)\d{2}\b"),
    "YYYY-MM": re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])\b"),
    "YYYY": re.compile(r"(?<![\w/-])(19|20)\d{2}\s*[-–—]\s*((19|20)\d{2}|present|current|now)\b", re.I),
}


def detect_date_formats(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    remaining = text
    # 先找完整月份，再移除，避免 "January" 被当成 "Jan"
    for name, pattern in DATE_FORMATS.items():
        found = pattern.findall(remaining)
        if found:
            counts[name] = len(found)
            remaining = pattern.sub(" ", remaining)
    return counts


def run_parse_checks(text: str, layout: LayoutInfo) -> tuple[int, list[Finding]]:
    findings: list[Finding] = []

    def add(check: str, status: str, message: str, points: int = 0, evidence: str | None = None) -> None:
        findings.append(
            Finding(
                category="parse",
                check=check,
                status=status,
                message=message,
                evidence=evidence,
                points_lost=points if status != "pass" else 0,
            )
        )

    # 1. 能否抽出文字
    if len(text.strip()) < 200 or layout.image_only_pages:
        pages = (
            tr("（第 {v} 页只有图片）", v=", ".join(map(str, layout.image_only_pages)))
            if layout.image_only_pages
            else ""
        )
        add(
            "text_extractable",
            "fail",
            tr(
                "抽出的文字太少{pages}，可能是扫描图档。多数 ATS 读不到图片里的字，请改用文字版 PDF 或 DOCX。",
                pages=pages,
            ),
            40,
        )
    else:
        add("text_extractable", "pass", tr("可以抽出文字（{v} 字元）。", v=len(text)))

    # 2. 档案格式
    add("file_format", "pass", tr("档案格式为 {v}，主流 ATS 都支援。", v=layout.file_kind.upper()))

    # 3. 表格
    if layout.table_count:
        add(
            "tables",
            "warn",
            tr(
                "发现 {table_count} 个表格。部分 ATS 会把表格内容读乱或略过，重要资讯建议放在一般段落。",
                table_count=layout.table_count,
            ),
            10,
        )
    else:
        add("tables", "pass", tr("没有表格。"))

    # 4. 双栏
    if layout.multi_column_pages:
        where = tr("页") if layout.file_kind == "pdf" else tr("节")
        add(
            "columns",
            "warn",
            tr(
                "第 {v} {where}看起来是双栏排版，ATS 可能把左右两栏的文字混在一起。",
                v=", ".join(map(str, layout.multi_column_pages)),
                where=where,
            ),
            15,
        )
    else:
        add("columns", "pass", tr("单栏排版。"))

    # 5. 文字方块
    if layout.text_box_count:
        add(
            "text_boxes",
            "warn",
            tr("发现 {text_box_count} 个文字方块，ATS 常常读不到里面的字。", text_box_count=layout.text_box_count),
            10,
        )
    elif layout.file_kind == "docx":
        add("text_boxes", "pass", tr("没有文字方块。"))

    # 6. 标准标题
    missing = [name for name, pattern in STANDARD_HEADINGS.items() if not pattern.search(text)]
    if not missing:
        add("standard_headings", "pass", tr("有 Experience、Education、Skills 等标准标题。"))
    else:
        names = ", ".join(m.capitalize() for m in missing)
        status = "fail" if "experience" in missing else "warn"
        add(
            "standard_headings",
            status,
            tr(
                "找不到标准标题：{names}。ATS 靠标题分段，建议使用常见名称（例如 Experience、Education、Skills）。",
                names=names,
            ),
            5 * len(missing) + (5 if status == "fail" else 0),
        )

    # 7. 联系方式
    email, phone, linkedin = EMAIL.search(text), PHONE.search(text), LINKEDIN.search(text)
    lacks = [n for n, m in (("Email", email), (tr("电话"), phone)) if not m]
    if lacks:
        add(
            "contact",
            "fail" if not email else "warn",
            tr("缺少联系方式：{v}。", v="、".join(lacks)),
            10 * (not email) + 5 * (not phone),
        )
    else:
        add("contact", "pass", tr("有 Email 与电话。"), evidence=email.group(0) if email else None)
    if not linkedin:
        add("linkedin", "warn", tr("没有 LinkedIn 网址（非必要，但很多职位会看）。"), 2)

    # 8. 日期格式一致
    formats = detect_date_formats(text)
    if not formats:
        add("date_format", "warn", tr("找不到经历日期。ATS 用日期计算年资，建议写上起讫月份与年份。"), 10)
    elif len(formats) > 1:
        detail = "、".join(tr("{k}（{v} 次）", k=k, v=v) for k, v in formats.items())
        add(
            "date_format",
            "warn",
            tr("日期格式不一致：{detail}。建议全部统一，例如都用 “Jan 2021”。", detail=detail),
            5,
            evidence=detail,
        )
    else:
        (fmt,) = formats
        add("date_format", "pass", tr("日期格式一致（{fmt}）。", fmt=fmt))

    # 9. 页数（只提示，不影响 ATS 读取）
    if layout.page_count and layout.page_count > 2:
        add("page_count", "warn", tr("共 {page_count} 页；多数职位建议 1–2 页。", page_count=layout.page_count), 0)

    score = max(0, 100 - sum(f.points_lost for f in findings))
    return score, findings
