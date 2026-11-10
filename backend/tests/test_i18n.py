"""介面语言：后端讯息与给模型的指令跟着 X-UI-Lang 走（预设英文）。"""

import re
import uuid

from app.core.i18n import get_lang, output_language, parse_lang, set_lang, tr
from app.core.i18n_en import EN
from app.resume_review.extract import extract
from app.resume_review.parse_checks import run_parse_checks
from tests.samples import SYNTHETIC_JD, make_pdf

PDF_MIME = "application/pdf"


def test_parse_lang_defaults_to_english():
    assert parse_lang(None) == "en"
    assert parse_lang("zh-CN") == "zh"
    assert parse_lang("EN") == "en"
    assert parse_lang("fr") == "en"


def test_tr_switches_language_and_fills_variables():
    set_lang("en")
    assert tr("找到 {v} 个职位页", v=3) == "found 3 job pages"
    assert tr("一句字典里没有的话") == "一句字典里没有的话"  # 没翻译就维持原文
    set_lang("zh")
    assert tr("找到 {v} 个职位页", v=3) == "找到 3 个职位页"
    assert get_lang() == "zh" and output_language() == "Simplified Chinese"


def test_dictionary_keeps_the_same_variables():
    for zh, en in EN.items():
        assert set(re.findall(r"\{(\w+)\}", zh)) == set(re.findall(r"\{(\w+)\}", en)), zh


def test_program_findings_in_english():
    set_lang("en")
    ex = extract(make_pdf(), PDF_MIME)
    _, findings = run_parse_checks(ex.text, ex.layout)
    text = " ".join(f.message for f in findings)
    assert not re.search(r"[一-鿿]", text), text
    assert output_language() == "English"


def test_api_errors_follow_header(client):
    missing = f"/api/jobs/{uuid.uuid4()}"
    assert client.get(missing, headers={"X-UI-Lang": "en"}).json()["detail"] == "Job not found"
    assert client.get(missing, headers={"X-UI-Lang": "zh"}).json()["detail"] == "找不到这个职位"


def test_model_is_asked_to_write_in_ui_language(client):
    client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), PDF_MIME)})
    job = client.post("/api/jobs/ingest", json={"jd_text": SYNTHETIC_JD}).json()["job"]
    client.fake.calls.clear()
    client.post(f"/api/jobs/{job['id']}/match", headers={"X-UI-Lang": "en"})
    system = next(
        m.content for msgs, _, _ in client.fake.calls for m in msgs if m.role == "system" and "fits a job" in m.content
    )
    assert "in English" in system and "{OUTPUT_LANGUAGE}" not in system
