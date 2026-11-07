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


def fake_responder(messages, json_mode):
    """依 schema 回传对应的假 JSON。"""
    title = (json_mode or {}).get("title")
    if title == "ParsedResume":
        return json.dumps(SYNTHETIC_PARSED)
    if title == "ContentReview":
        return CONTENT_REVIEW_JSON
    if title == "RoleSkills":
        return ROLE_SKILLS_JSON
    return "ok"
