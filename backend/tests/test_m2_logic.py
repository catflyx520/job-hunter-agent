"""M2 纯逻辑测试：SSRF 防护、正规化、硬性排除、证据核对、评分规则、截图验证、草稿真实性检查。"""

import io
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core import fetch
from app.graphs.materials import Citation, Draft, FactItem, NeedItem, verify_draft
from app.jobs.exclusion import check_exclusions
from app.jobs.extract import JobExtraction, verify_evidence
from app.jobs.match import location_part, recency_part, recommend
from app.jobs.normalize import canonical_key, location_tier, normalize_company, site_for_url
from app.materials.images import ImageError, validate_images
from app.rag.retrieve import Evidence, _or_query, rrf
from app.schemas.profile import JobPreferences
from tests.samples import JOB_EXTRACTION, SYNTHETIC_JD

# ---------- SSRF ----------


def _addr(ip):
    return lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.mark.parametrize(
    "url, ip",
    [
        ("https://internal.example/job", "10.0.0.5"),
        ("https://localhost/job", "127.0.0.1"),
        ("http://metadata.example/latest", "169.254.169.254"),
        ("https://v6.example/job", "::1"),
    ],
)
def test_blocks_private_addresses(monkeypatch, url, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _addr(ip))
    with pytest.raises(fetch.FetchError, match="内网"):
        fetch.public_target(url)


@pytest.mark.parametrize(
    "url", ["ftp://example.com/x", "https://user:pw@example.com/", "https://example.com:8443/", "javascript:alert(1)"]
)
def test_rejects_bad_urls(url):
    with pytest.raises(fetch.FetchError):
        fetch.public_target(url)


def test_redirect_to_private_ip_is_blocked(monkeypatch):
    def resolver(host, *a, **k):
        ip = "10.1.2.3" if host == "evil.internal" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    class Redirect:
        status = 302

        def getheader(self, name, default=None):
            return "https://evil.internal/admin" if name == "Location" else default

    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Redirect()

        def close(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    monkeypatch.setattr(fetch.http.client, "HTTPSConnection", Conn)
    with pytest.raises(fetch.FetchError, match="内网"):
        fetch.fetch_page("https://jobs.example.com/123")


def test_html_to_text_drops_scripts_and_keeps_structure():
    text, title = fetch.html_to_text(
        "<html><head><title>Job</title><script>evil()</script></head><body><h1>Engineer</h1>"
        "<ul><li>Python</li><li>SQL</li></ul><style>x{}</style></body></html>"
    )
    assert title == "Job"
    assert "evil" not in text and "x{}" not in text
    assert "Engineer" in text and "- Python" in text


# ---------- 正规化 ----------


@pytest.mark.parametrize(
    "raw, norm",
    [
        ("Acme Analytics, Inc.", "acme analytics"),
        ("ACME ANALYTICS INC", "acme analytics"),
        ("Henry Labs, Inc. d/b/a Clerkie", "henry labs"),
        ("The Example Company LLC", "example"),
        ("AT&T Services, Inc.", "at and t services"),
        ("Example Holdings Corp", "example"),
    ],
)
def test_normalize_company(raw, norm):
    assert normalize_company(raw) == norm


def test_canonical_key_prefers_requisition():
    assert canonical_key("acme", "Sr. Engineer", "LA", "R-123") == "req:acme:r-123"
    a = canonical_key("acme", "Sr. Engineer", "Los Angeles, CA")
    b = canonical_key("acme", "Senior Engineer", "los angeles ca")
    assert a == b and a.startswith("h:")


def test_site_for_url():
    assert site_for_url("https://www.linkedin.com/jobs/view/1") == "linkedin"
    assert site_for_url("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert site_for_url("https://careers.acme.com/1") == "manual"


def test_location_tier():
    prefs = ["Los Angeles 都会区", "Orange County", "Remote (California)"]
    assert location_tier("Los Angeles, CA", "hybrid", prefs) == 1
    assert location_tier("Irvine, Orange County, CA", "onsite", prefs) == 2
    assert location_tier("Anywhere", "remote", prefs) == 3
    assert location_tier("Seattle, WA", "onsite", prefs) is None


# ---------- JD 证据核对 ----------


def test_verify_evidence_downgrades_unquoted_claims():
    ex = JobExtraction.model_validate(JOB_EXTRACTION)
    assert verify_evidence(ex, SYNTHETIC_JD) == []
    assert ex.sponsorship_policy == "explicit_no"

    fake = JobExtraction.model_validate(
        {
            **JOB_EXTRACTION,
            "sponsorship_evidence": "We never sponsor anyone ever.",
            "new_grad_only": True,
            "new_grad_evidence": "Class of 2026 only",
        }
    )
    notes = verify_evidence(fake, SYNTHETIC_JD)
    assert fake.sponsorship_policy == "unclear" and fake.new_grad_only is False
    assert len(notes) == 2


# ---------- 硬性排除 ----------


def _job(**kw):
    base = dict(
        sponsorship_policy="unclear",
        citizenship_required=False,
        employment_type="full_time",
        salary_min=None,
        salary_max=None,
        salary_period=None,
        new_grad_only=False,
        status="unverified",
    )
    return SimpleNamespace(**{**base, **kw})


def _prefs(**kw):
    return JobPreferences.model_validate(
        {
            "work_authorization": {
                "authorized_in_us": True,
                "needs_sponsorship_now": False,
                "needs_sponsorship_future": True,
            },
            **kw,
        }
    )


def test_exclusions():
    prefs = _prefs(min_salary=120000)
    assert check_exclusions(_job(sponsorship_policy="explicit_no"), prefs).reasons == ["explicit_no_sponsorship"]
    assert "sponsorship_unclear" in check_exclusions(_job(), prefs).flags
    assert check_exclusions(_job(employment_type="contract"), prefs).reasons == ["employment_type"]
    assert check_exclusions(_job(salary_min=90000, salary_max=110000, salary_period="year"), prefs).reasons == [
        "salary_below_minimum"
    ]
    partial = check_exclusions(_job(salary_min=100000, salary_max=140000, salary_period="year"), prefs)
    assert partial.reasons == [] and "salary_partially_below" in partial.flags
    hourly = check_exclusions(_job(salary_min=70, salary_max=80, salary_period="hour"), prefs)
    assert hourly.reasons == []  # 70×2080 = 145,600
    assert check_exclusions(_job(new_grad_only=True), prefs).reasons == ["new_grad_only"]
    assert check_exclusions(_job(citizenship_required=True), prefs).reasons == ["citizenship_required"]
    # 不需要 sponsorship 的公民：sponsorship 写不提供也不排除
    citizen = _prefs(
        work_authorization={"authorized_in_us": True, "needs_sponsorship_now": False, "needs_sponsorship_future": False}
    )
    assert check_exclusions(_job(sponsorship_policy="explicit_no", citizenship_required=True), citizen).reasons == []


# ---------- 评分规则 ----------


def test_program_scored_parts():
    prefs = _prefs(locations=["Los Angeles", "Remote"], work_modes=["hybrid", "remote"])
    job = SimpleNamespace(
        work_mode="hybrid", location_tier=1, posted_at=None, posted_text="3 days ago", verification_source="pasted"
    )
    assert location_part(job, prefs)["score"] == 10
    job.work_mode = "onsite"
    assert location_part(job, prefs)["score"] == 0
    r = recency_part(job)
    assert r["score"] == 5 and "3 days ago" in r["reason"]
    job.posted_at, job.verification_source = datetime.now(UTC) - timedelta(days=2), "employer_site"
    assert recency_part(job)["score"] == 10


def test_recommend_respects_exclusion():
    ok = SimpleNamespace(excluded=False)
    bad = SimpleNamespace(excluded=True)
    assert recommend(80, ok) == "apply" and recommend(60, ok) == "maybe" and recommend(40, ok) == "skip"
    assert recommend(95, bad) == "skip"


def test_rrf_and_tsquery():
    assert rrf([["a", "b", "c"], ["c", "a"]])[:2] == ["a", "c"]
    assert _or_query(["Python", "C++", "Node.js"]) == "c | nodejs | python"


# ---------- 截图 ----------


def _img(fmt, size=(20, 10), **kw):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, fmt, **kw)
    return buf.getvalue()


def test_validate_images():
    ok = validate_images([_img("PNG"), _img("JPEG"), _img("WEBP")])
    assert [i.mime for i in ok] == ["image/png", "image/jpeg", "image/webp"]
    with pytest.raises(ImageError, match="PNG / JPG / WebP"):
        validate_images([_img("GIF")])
    with pytest.raises(ImageError, match="损坏"):
        validate_images([b"<svg xmlns='http://www.w3.org/2000/svg'/>"])
    with pytest.raises(ImageError, match="最多"):
        validate_images([_img("PNG")] * 7)
    frames = io.BytesIO()
    Image.new("RGB", (5, 5)).save(frames, "WEBP", save_all=True, append_images=[Image.new("RGB", (5, 5), "red")])
    with pytest.raises(ImageError, match="动图"):
        validate_images([frames.getvalue()])


# ---------- 草稿真实性检查 ----------


def test_verify_draft_flags_unsupported_claims_and_numbers():
    evidence = [
        Evidence(
            "c1", "experience[0].bullets[0]", "experience", "Built a FastAPI service that processes 2M events per day."
        )
    ]
    facts = [FactItem("notice_period", "Notice?", "2 weeks")]
    draft = Draft(
        text="I built a service handling 2M events daily. My notice is 2 weeks. I grew revenue 300%. "
        "I can start [NEEDS CONFIRMATION: start date].",
        citations=[
            Citation(sentence="I built a service handling 2M events daily.", evidence_ids=["c1"]),
            Citation(sentence="My notice is 2 weeks.", fact_keys=["notice_period"]),
            Citation(sentence="I grew revenue 300%.", evidence_ids=["ghost"]),
        ],
        needs_confirmation=[NeedItem(item="期望薪资", why="未提供")],
    )
    citations, needs, used = verify_draft(draft, evidence, facts, reference="")
    assert used == ["notice_period"]
    assert citations[2]["supported"] is False and citations[2]["chunk_ids"] == []
    items = " ".join(n["item"] for n in needs)
    assert "300%" in items  # 找不到来源的数字
    assert "2m" not in items.lower()  # 有来源的数字不列
    assert "start date" in items  # 占位符
    assert "期望薪资" in items  # 模型自己列的保留
    assert any("不存在的证据" in n["why"] for n in needs)
