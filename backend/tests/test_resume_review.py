import pytest

from app.core import security
from app.graphs.resume_review import run_review
from app.llm.fake import FakeProvider
from app.rag.chunks import make_chunks
from app.resume_review.content import bullet_stats
from app.resume_review.extract import DOCX_MIME, PDF_MIME, UnsupportedFile, extract, sniff_mime
from app.resume_review.parse_checks import detect_date_formats, run_parse_checks
from app.resume_review.structure import unverified_items
from app.schemas.resume import ParsedResume
from tests.samples import SYNTHETIC_PARSED, fake_responder, make_docx, make_pdf


def _status(findings, check):
    return next(f for f in findings if f.check == check).status


def test_sniff_mime_uses_content_not_extension():
    assert sniff_mime(make_pdf(), "x.docx") == PDF_MIME
    assert sniff_mime(make_docx(), "x.pdf") == DOCX_MIME
    with pytest.raises(UnsupportedFile):
        sniff_mime(b"<svg></svg>", "resume.pdf")


def test_clean_pdf_passes_parse_checks():
    ex = extract(make_pdf(), PDF_MIME)
    assert "Jordan Rivera" in ex.text
    score, findings = run_parse_checks(ex.text, ex.layout)
    assert _status(findings, "text_extractable") == "pass"
    assert _status(findings, "columns") == "pass"
    assert _status(findings, "standard_headings") == "pass"
    assert _status(findings, "contact") == "pass"
    assert _status(findings, "date_format") == "warn"  # "Jan 2022" 与 "2015 - 2019" 混用
    assert score == 100 - sum(f.points_lost for f in findings)
    assert all(f.message for f in findings)


def test_two_column_pdf_is_flagged():
    lines = [f"Left column text item number {i} here and more words      Right side {i}" for i in range(40)]
    ex = extract(make_pdf(lines, two_column=True), PDF_MIME)
    _, findings = run_parse_checks(ex.text, ex.layout)
    assert _status(findings, "columns") == "warn"


def test_image_only_pdf_fails_extractable():
    ex = extract(make_pdf(["", ""]), PDF_MIME)
    score, findings = run_parse_checks(ex.text, ex.layout)
    assert _status(findings, "text_extractable") == "fail"
    assert score <= 60


def test_docx_table_is_flagged():
    ex = extract(make_docx(with_table=True), DOCX_MIME)
    _, findings = run_parse_checks(ex.text, ex.layout)
    assert _status(findings, "tables") == "warn"
    assert _status(findings, "text_boxes") == "pass"


def test_date_format_detection():
    assert detect_date_formats("January 2020 - March 2021") == {"Month YYYY": 2}
    assert detect_date_formats("Jan 2020 – Mar 2021, 03/2019") == {"Mon YYYY": 2, "MM/YYYY": 1}
    assert detect_date_formats("2015 - 2019") == {"YYYY": 1}


def test_unverified_items_flags_rewritten_bullets():
    parsed = ParsedResume.model_validate(SYNTHETIC_PARSED)
    raw = "\n".join(make_pdf.__globals__["SYNTHETIC_LINES"])
    assert unverified_items(parsed, raw) == []
    parsed.experience[0].bullets.append("Won a Turing Award.")
    assert unverified_items(parsed, raw) == ["Won a Turing Award."]


def test_make_chunks_has_source_refs():
    chunks = make_chunks(ParsedResume.model_validate(SYNTHETIC_PARSED))
    refs = [c.source_ref for c in chunks]
    assert "summary" in refs and "experience[1].bullets[0]" in refs and "projects[0].bullets[0]" in refs
    first = next(c for c in chunks if c.source_ref == "experience[0].bullets[0]")
    assert first.text.startswith("Senior Software Engineer @ Acme Analytics: Built")


def test_bullet_stats():
    stats = bullet_stats(ParsedResume.model_validate(SYNTHETIC_PARSED))
    assert stats.total == 6
    assert stats.quantified == 4
    assert stats.weak_start == ["Responsible for code reviews."]


def test_review_graph_merges_all_three_parts():
    ex = extract(make_pdf(), PDF_MIME)
    out = run_review(
        FakeProvider(fake_responder), ex.text, ParsedResume.model_validate(SYNTHETIC_PARSED), ex.layout, "Backend Engineer"
    )
    assert out.content_score == 20 + 15 + 22 + 25
    # Python(2) + React(2) 命中，Kubernetes(2) + GraphQL(1) 未命中 → 4/7
    assert out.keyword_score == round(100 * 4 / 7)
    categories = {f.category for f in out.findings}
    assert categories == {"parse", "content", "keyword"}
    kw = next(f for f in out.findings if f.category == "keyword")
    assert "Kubernetes" in kw.message and "确实具备" in kw.message


def test_review_without_target_role_skips_keywords():
    ex = extract(make_pdf(), PDF_MIME)
    out = run_review(FakeProvider(fake_responder), ex.text, ParsedResume.model_validate(SYNTHETIC_PARSED), ex.layout, None)
    assert out.keyword_score is None
    assert any(f.category == "keyword" and "没有指定目标职位" in f.message for f in out.findings)


def test_secret_roundtrip_and_last4():
    token = security.encrypt_secret("sk-test-1234")
    assert b"sk-test" not in token
    assert security.decrypt_secret(token) == "sk-test-1234"
    assert security.last4("sk-test-1234") == "1234"
