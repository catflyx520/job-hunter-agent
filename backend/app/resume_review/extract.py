"""从 PDF / DOCX 抽文字，并收集版面资讯（给可解析度检查用）。纯程序，不用 LLM。"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from app.core.i18n import tr

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_MIMES = {PDF_MIME: ".pdf", DOCX_MIME: ".docx"}


class UnsupportedFile(ValueError):
    pass


@dataclass
class LayoutInfo:
    """版面特征。None 表示无法判断（未知就是未知）。"""

    file_kind: str
    page_count: int | None = None
    table_count: int = 0
    text_box_count: int = 0
    multi_column_pages: list[int] = field(default_factory=list)
    image_only_pages: list[int] = field(default_factory=list)


@dataclass
class Extracted:
    text: str
    layout: LayoutInfo


def sniff_mime(data: bytes, filename: str) -> str:
    """以档案内容判断格式，不信任副档名或浏览器给的 content-type。"""
    if data.startswith(b"%PDF-"):
        return PDF_MIME
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    return DOCX_MIME
        except zipfile.BadZipFile:
            pass
    raise UnsupportedFile(tr("只支援 PDF 或 DOCX（{filename} 的内容不是这两种格式）。", filename=filename))


def extract(data: bytes, mime: str) -> Extracted:
    if mime == PDF_MIME:
        return _extract_pdf(data)
    if mime == DOCX_MIME:
        return _extract_docx(data)
    raise UnsupportedFile(tr("只支援 PDF 或 DOCX。"))


def _extract_pdf(data: bytes) -> Extracted:
    import pdfplumber

    layout = LayoutInfo(file_kind="pdf")
    pages_text: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            layout.page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages_text.append(text)
                words = page.extract_words()
                if len(text.strip()) < 20 and page.images:
                    layout.image_only_pages.append(i)
                layout.table_count += len(page.find_tables())
                if _looks_multi_column(words, float(page.width)):
                    layout.multi_column_pages.append(i)
    except Exception as exc:  # noqa: BLE001 - pdfminer 会丢各种例外
        raise UnsupportedFile(tr("PDF 无法读取，档案可能损坏或加密。")) from exc
    return Extracted(text="\n".join(pages_text).strip(), layout=layout)


def _looks_multi_column(words: list[dict], page_width: float) -> bool:
    """同一行左右两半都有文字、且中间有明显空白的行占多数 → 视为双栏。"""
    if len(words) < 40:
        return False
    rows: dict[int, list[dict]] = {}
    for w in words:
        rows.setdefault(round(float(w["top"]) / 3), []).append(w)
    mid = page_width / 2
    split_rows = 0
    for row in rows.values():
        row.sort(key=lambda w: float(w["x0"]))
        left = [w for w in row if float(w["x1"]) < mid]
        right = [w for w in row if float(w["x0"]) > mid]
        if left and right:
            gap = float(right[0]["x0"]) - float(left[-1]["x1"])
            if gap > page_width * 0.08:
                split_rows += 1
    return len(rows) > 0 and split_rows / len(rows) > 0.35


def _extract_docx(data: bytes) -> Extracted:
    import docx

    layout = LayoutInfo(file_kind="docx")
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedFile(tr("DOCX 无法读取，档案可能损坏。")) from exc

    lines = [p.text for p in document.paragraphs]
    layout.table_count = len(document.tables)
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))

    xml = document.element.xml
    layout.text_box_count = xml.count("<w:txbxContent")
    for i, section in enumerate(document.sections, start=1):
        cols = section._sectPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cols")
        if cols is not None:
            num = cols.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num")
            if num and int(num) > 1:
                layout.multi_column_pages.append(i)
    return Extracted(text="\n".join(line for line in lines).strip(), layout=layout)
