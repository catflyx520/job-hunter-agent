"""合成的测试履历（虚构人物，不含任何真实个人资料）。"""

from __future__ import annotations

import io
import json

SYNTHETIC_LINES = [
    "Jordan Rivera",
    "jordan.rivera@example.com | (555) 010-2030 | Los Angeles, CA | linkedin.com/in/jordan-rivera-example",
    "",
    "Summary",
    "Full-stack engineer with 5 years building web products with Python and React.",
    "",
    "Experience",
    "Senior Software Engineer, Acme Analytics — Los Angeles, CA",
    "Jan 2022 - Present",
    "- Built a FastAPI service that processes 2M events per day, cutting report latency by 40%.",
    "- Led migration of 12 React pages to TypeScript, reducing production bugs by 30%.",
    "- Responsible for code reviews.",
    "Software Engineer, Example Labs — Remote",
    "Jun 2019 - Dec 2021",
    "- Designed PostgreSQL schemas and REST APIs for a scheduling product used by 300 clinics.",
    "- Added CI pipelines with GitHub Actions and Docker.",
    "",
    "Projects",
    "Budget Buddy - personal finance tracker (Python, React)",
    "- Implemented OCR receipt import with 95% field accuracy on a test set.",
    "",
    "Skills",
    "Python, FastAPI, React, TypeScript, PostgreSQL, Docker, AWS, Git",
    "",
    "Education",
    "B.S. Computer Science, State University, 2015 - 2019",
]

SYNTHETIC_PARSED = {
    "basics": {
        "name": "Jordan Rivera",
        "email": "jordan.rivera@example.com",
        "phone": "(555) 010-2030",
        "location": "Los Angeles, CA",
        "links": [{"label": "LinkedIn", "url": "linkedin.com/in/jordan-rivera-example"}],
    },
    "summary": "Full-stack engineer with 5 years building web products with Python and React.",
    "skills": ["Python", "FastAPI", "React", "TypeScript", "PostgreSQL", "Docker", "AWS", "Git"],
    "experience": [
        {
            "company": "Acme Analytics",
            "title": "Senior Software Engineer",
            "location": "Los Angeles, CA",
            "start": "Jan 2022",
            "end": "Present",
            "bullets": [
                "Built a FastAPI service that processes 2M events per day, cutting report latency by 40%.",
                "Led migration of 12 React pages to TypeScript, reducing production bugs by 30%.",
                "Responsible for code reviews.",
            ],
        },
        {
            "company": "Example Labs",
            "title": "Software Engineer",
            "location": "Remote",
            "start": "Jun 2019",
            "end": "Dec 2021",
            "bullets": [
                "Designed PostgreSQL schemas and REST APIs for a scheduling product used by 300 clinics.",
                "Added CI pipelines with GitHub Actions and Docker.",
            ],
        },
    ],
    "projects": [
        {
            "name": "Budget Buddy",
            "description": "personal finance tracker",
            "tech": ["Python", "React"],
            "bullets": ["Implemented OCR receipt import with 95% field accuracy on a test set."],
        }
    ],
    "education": [
        {
            "school": "State University",
            "degree": "B.S.",
            "field": "Computer Science",
            "start": "2015",
            "end": "2019",
            "details": [],
        }
    ],
}


def make_pdf(lines: list[str] | None = None, two_column: bool = False) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    lines = SYNTHETIC_LINES if lines is None else lines
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    y = height - 50
    for line in lines:
        c.setFont("Helvetica", 10)
        if two_column:
            c.drawString(40, y, line[:45])
            c.drawString(width / 2 + 40, y, (line[45:] or line)[:45])
        else:
            c.drawString(40, y, line.replace("—", "-"))
        y -= 14
    c.save()
    return buf.getvalue()


def make_docx(with_table: bool = False) -> bytes:
    import docx

    d = docx.Document()
    for line in SYNTHETIC_LINES:
        d.add_paragraph(line)
    if with_table:
        t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text = "Languages"
        t.rows[0].cells[1].text = "English, Spanish"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


CONTENT_REVIEW_JSON = json.dumps(
    {
        "quantified_results": {"score": 20, "status": "pass", "message": "多数 bullet 有数字。", "examples": []},
        "action_verbs": {
            "score": 15,
            "status": "warn",
            "message": "有一条以 Responsible for 开头。",
            "examples": ["Responsible for code reviews."],
        },
        "specificity": {"score": 22, "status": "pass", "message": "内容具体。", "examples": []},
        "length": {"score": 25, "status": "pass", "message": "一页，长度合适。", "examples": []},
    }
)

ROLE_SKILLS_JSON = json.dumps(
    {
        "skills": [
            {"name": "Python", "aliases": [], "importance": "core"},
            {"name": "React", "aliases": ["React.js"], "importance": "core"},
            {"name": "Kubernetes", "aliases": ["k8s"], "importance": "core"},
            {"name": "GraphQL", "aliases": [], "importance": "nice"},
        ]
    }
)


SYNTHETIC_JD = """Senior Backend Engineer - Example Robotics, Inc.
Location: Los Angeles, CA (Hybrid)
Full-time. Salary range: $150,000 - $180,000 per year.
Posted 3 days ago.

About the role
You will build Python and FastAPI services that process telemetry from our robot fleet.

Requirements
- 5+ years building backend services in Python
- Experience with PostgreSQL and Docker
- Kubernetes experience is a plus

We are unable to sponsor visas for this position.
Example Robotics is an equal opportunity employer.
"""

JOB_EXTRACTION = {
    "company": "Example Robotics, Inc.",
    "is_staffing_agency": False,
    "company_website": "https://example-robotics.test",
    "title": "Senior Backend Engineer",
    "requisition_id": "",
    "seniority": "senior",
    "location_text": "Los Angeles, CA",
    "work_mode": "hybrid",
    "employment_type": "full_time",
    "salary_min": 150000,
    "salary_max": 180000,
    "salary_currency": "USD",
    "salary_period": "year",
    "posted_text": "3 days ago",
    "sponsorship_policy": "explicit_no",
    "sponsorship_evidence": "We are unable to sponsor visas for this position.",
    "new_grad_only": False,
    "new_grad_evidence": "",
    "citizenship_required": False,
    "citizenship_evidence": "",
    "clearance_required": False,
    "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "nice_to_have_skills": ["Kubernetes"],
    "years_experience_min": 5,
    "apply_url": "",
}


def _evidence_ids(messages) -> list[str]:
    """从提示词里抓出 [id] 形式的证据编号（假模型用来引用）。"""
    import re

    text = messages[-1].content
    return re.findall(r"^\[([^\]]+)\] \((?:experience|project|summary|skills|education)\)", text, re.M)


def fake_responder(messages, json_mode):
    """依 schema 回传对应的假 JSON。"""
    title = (json_mode or {}).get("title")
    if title == "ParsedResume":
        return json.dumps(SYNTHETIC_PARSED)
    if title == "ContentReview":
        return CONTENT_REVIEW_JSON
    if title == "RoleSkills":
        return ROLE_SKILLS_JSON
    if title == "JobExtraction":
        return json.dumps(_extraction_for(messages[-1].content))
    if title == "SearchLeads":
        return json.dumps(SEARCH_LEADS.get(_site_name(messages[-1].content), {"jobs": []}))
    if title == "LLMMatch":
        ids = _evidence_ids(messages)
        return json.dumps(
            {
                "role": {"score": 24, "reason": "后端服务经验相符。"},
                "tech": {"score": 22, "reason": "Python、FastAPI、PostgreSQL 都有。"},
                "experience": {"score": 15, "reason": "资历大致相符。"},
                "reasons": [
                    {"text": "做过处理大量事件的 FastAPI 服务。", "evidence_ids": ids[:1]},
                    {"text": "没有证据的理由。", "evidence_ids": ["not-a-real-id"]},
                ],
                "gaps": [{"text": "履历没有 Kubernetes 经验。", "severity": "medium"}],
            }
        )
    if title == "Draft":
        ids = _evidence_ids(messages)
        return json.dumps(
            {
                "text": "I built a FastAPI service that processes 2M events per day. I can start "
                "[NEEDS CONFIRMATION: start date]. I also led a team of 40 engineers.",
                "citations": [
                    {
                        "sentence": "I built a FastAPI service that processes 2M events per day.",
                        "evidence_ids": ids[:1],
                    },
                    {"sentence": "I also led a team of 40 engineers.", "evidence_ids": []},
                ],
                "needs_confirmation": [],
            }
        )
    return "ok"


# ---------- M3 搜索用的合成资料 ----------


def make_jd(title: str, company: str, location: str, extra: str = "") -> str:
    """合成 JD：第一行职称，接着公司与地点（假模型会照这个格式抽取）。"""
    body = [
        title,
        f"Company: {company}",
        f"Location: {location}",
        "",
        "We build Python and FastAPI services backed by PostgreSQL. Full-time role.",
        "You will design APIs, own data pipelines and work with product teams.",
        "Requirements: 3+ years of backend development in Python; SQL; cloud experience.",
        extra,
    ]
    return chr(10).join(body)


def _extraction_for(prompt: str) -> dict:
    import re

    jd = prompt.split("<<<" + chr(10), 1)[-1]
    if jd.startswith("Senior Backend Engineer - Example Robotics"):
        return JOB_EXTRACTION
    lines = jd.splitlines()
    company = re.search(r"^Company: (.+)$", jd, re.M)
    location = re.search(r"^Location: (.+)$", jd, re.M)
    loc = location.group(1) if location else ""
    return {
        **JOB_EXTRACTION,
        "company": company.group(1) if company else "",
        "company_website": "",
        "title": lines[0].strip() if lines else "",
        "seniority": "mid",
        "location_text": loc,
        "work_mode": "remote" if "remote" in loc.lower() else "onsite",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "salary_period": "unknown",
        "posted_text": "",
        "sponsorship_policy": "unclear",
        "sponsorship_evidence": "",
    }


def _site_name(prompt: str) -> str:
    import re

    m = re.search(r"^Site: (.+?) \(", prompt, re.M)
    return m.group(1) if m else ""


# 假模型的搜索结果：依网站名称回传
SEARCH_LEADS = {
    "LinkedIn": {
        "jobs": [
            {"url": "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind-1111111111?trk=x",
             "title": "Backend Engineer", "company": "Northwind Labs", "posted_text": "2 days ago"},
            {"url": "https://www.linkedin.com/company/northwind", "title": "Northwind Labs"},
            {"url": "https://www.linkedin.com/jobs/view/2222222222", "title": "Backend Engineer", "company": "Blocked Co"},
        ],
        "note": "",
    },
    "Indeed": {"jobs": [{"url": "https://www.indeed.com/viewjob?jk=abcdef0123456789&from=serp", "title": "x"}]},
}  # fmt: skip

PAGES = {
    "https://linkedin.com/jobs/view/backend-engineer-at-northwind-1111111111": make_jd(
        "Backend Engineer", "Northwind Labs", "Los Angeles, CA"
    ),
    "https://indeed.com/viewjob?jk=abcdef0123456789": SYNTHETIC_JD,
}

GREENHOUSE_BOARD = {
    "jobs": [
        {
            "id": 101,
            "title": "Backend Engineer, Platform",
            "absolute_url": "https://job-boards.greenhouse.io/acmeco/jobs/101",
            "location": {"name": "Remote - US"},
            "updated_at": "2026-11-01T10:00:00Z",
            "content": "&lt;p&gt;Design Python APIs for our platform team.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;PostgreSQL&lt;/li&gt;&lt;/ul&gt;",
        },
        {
            "id": 102,
            "title": "Account Executive",
            "absolute_url": "https://job-boards.greenhouse.io/acmeco/jobs/102",
            "location": {"name": "New York"},
            "content": "Sell things.",
        },
    ]
}
