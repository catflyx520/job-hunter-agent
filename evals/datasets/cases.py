"""Evals 资料集（全部合成、虚构）：5 个求职者 × 每人 8 份 JD = 40 个标注案例。

每个案例的标注：
- gold：JD 里真正写了什么（程序组 JD 时一起产生，抽取准确率拿它比对）
- expected_exclusions：这个求职者对这份 JD 应该触发的硬性排除（人工标注）
- expected：建议等级 apply / maybe / skip（人工标注；被排除的一律 skip）

标注规则写在每个案例的 why，请作者过目、调整。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------- 5 个虚构求职者 ----------


def _resume(name, location, summary, skills, experience, education, projects=()) -> dict:
    return {
        "basics": {"name": name, "email": f"{name.split()[0].lower()}@example.com", "phone": "", "location": location,
                   "links": []},
        "summary": summary,
        "skills": skills,
        "experience": [
            {"company": c, "title": t, "location": loc, "start": s, "end": e, "bullets": b}
            for c, t, loc, s, e, b in experience
        ],
        "projects": [{"name": n, "description": d, "tech": tech, "bullets": b} for n, d, tech, b in projects],
        "education": [{"school": s, "degree": d, "field": f, "start": a, "end": b, "details": []} for s, d, f, a, b in education],
    }  # fmt: skip


PERSONAS: dict[str, dict[str, Any]] = {
    "jordan": {
        "resume": _resume(
            "Jordan Rivera", "Los Angeles, CA",
            "Full-stack engineer with 5 years building web products with Python and React.",
            ["Python", "FastAPI", "React", "TypeScript", "PostgreSQL", "Docker", "AWS", "Git"],
            [
                ("Acme Analytics", "Senior Software Engineer", "Los Angeles, CA", "Jan 2022", "Present", [
                    "Built a FastAPI service that processes 2M events per day, cutting report latency by 40%.",
                    "Led migration of 12 React pages to TypeScript, reducing production bugs by 30%."]),
                ("Example Labs", "Software Engineer", "Remote", "Jun 2019", "Dec 2021", [
                    "Designed PostgreSQL schemas and REST APIs for a scheduling product used by 300 clinics.",
                    "Added CI pipelines with GitHub Actions and Docker."]),
            ],
            [("State University", "B.S.", "Computer Science", "2015", "2019")],
        ),
        "preferences": {
            "target_roles": ["Full Stack Engineer", "Backend Engineer"], "seniority": ["mid", "senior"],
            "locations": ["Los Angeles", "Remote"], "work_modes": ["onsite", "hybrid", "remote"],
            "employment_types": ["full_time"], "min_salary": 100000, "exclude_new_grad_only": True,
            "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False,
                                   "needs_sponsorship_future": True},
        },
        "facts": [("notice_period", "How much notice do you need?", "2 weeks")],
    },
    "sam": {
        "resume": _resume(
            "Sam Okafor", "Chicago, IL",
            "Data engineer with 3 years building batch and streaming pipelines on AWS.",
            ["Python", "SQL", "Apache Spark", "Airflow", "dbt", "Snowflake", "AWS", "Kafka"],
            [
                ("Northwind Retail", "Data Engineer", "Chicago, IL", "Mar 2023", "Present", [
                    "Built Airflow and dbt pipelines that load 400 GB per day into Snowflake.",
                    "Cut nightly Spark job runtime from 5 hours to 90 minutes."]),
                ("Contoso Health", "Data Analyst", "Chicago, IL", "Jun 2021", "Feb 2023", [
                    "Wrote SQL models for claims reporting used by 6 teams."]),
            ],
            [("Lakeview University", "M.S.", "Information Systems", "2019", "2021")],
        ),
        "preferences": {
            "target_roles": ["Data Engineer", "Analytics Engineer"], "seniority": ["mid"],
            "locations": ["Remote", "Chicago"], "work_modes": ["hybrid", "remote"],
            "employment_types": ["full_time"], "min_salary": 110000, "exclude_new_grad_only": True,
            "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": True,
                                   "needs_sponsorship_future": True},
        },
        "facts": [("start_date", "When can you start?", "June 1, 2027")],
    },
    "mei": {
        "resume": _resume(
            "Mei Tanaka", "Seattle, WA",
            "iOS engineer with 7 years shipping consumer apps in Swift and SwiftUI.",
            ["Swift", "SwiftUI", "Objective-C", "UIKit", "Core Data", "XCTest", "Kotlin"],
            [
                ("Bluebird Apps", "Senior iOS Engineer", "Seattle, WA", "Feb 2021", "Present", [
                    "Led the SwiftUI rewrite of a banking app with 1.2M monthly users.",
                    "Raised crash-free sessions from 98.1% to 99.7%."]),
                ("Fabrikam Mobile", "iOS Engineer", "Seattle, WA", "Jul 2017", "Jan 2021", [
                    "Built offline sync with Core Data for a field-service app."]),
            ],
            [("Cascade State University", "B.S.", "Software Engineering", "2013", "2017")],
        ),
        "preferences": {
            "target_roles": ["iOS Engineer", "Mobile Engineer"], "seniority": ["senior", "staff_plus"],
            "locations": ["Seattle", "Remote"], "work_modes": ["hybrid", "remote"],
            "employment_types": ["full_time"], "min_salary": 140000, "exclude_new_grad_only": True,
            "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False,
                                   "needs_sponsorship_future": False},
        },
        "facts": [("notice_period", "How much notice do you need?", "3 weeks")],
    },
    "alex": {
        "resume": _resume(
            "Alex Moreno", "New York, NY",
            "Backend engineer with 1 year of Java and Spring Boot experience after a CS degree.",
            ["Java", "Spring Boot", "MySQL", "REST", "Docker", "JUnit"],
            [
                ("Tailspin Payments", "Software Engineer I", "New York, NY", "Jul 2025", "Present", [
                    "Built Spring Boot endpoints for refund processing handling 50k requests per day."]),
                ("Tailspin Payments", "Software Engineering Intern", "New York, NY", "Jun 2024", "Aug 2024", [
                    "Added JUnit tests that raised coverage of the ledger service to 80%."]),
            ],
            [("Hudson City College", "B.S.", "Computer Science", "2021", "2025")],
            [("Bookshelf", "library catalog web app", ["Java", "Spring Boot", "MySQL"], [
                "Implemented search over 20k titles with MySQL full-text indexes."])],
        ),
        "preferences": {
            "target_roles": ["Backend Engineer", "Software Engineer"], "seniority": ["junior"],
            "locations": ["New York", "New Jersey", "Remote"], "work_modes": ["onsite", "hybrid", "remote"],
            "employment_types": ["full_time"], "min_salary": 80000, "exclude_new_grad_only": False,
            "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False,
                                   "needs_sponsorship_future": True},
        },
        "facts": [],
    },
    "chris": {
        "resume": _resume(
            "Chris Lee", "San Jose, CA",
            "Machine learning engineer with 4 years training and serving models with PyTorch.",
            ["Python", "PyTorch", "Kubernetes", "MLflow", "Ray", "AWS SageMaker", "SQL"],
            [
                ("Woodgrove AI", "Machine Learning Engineer", "San Jose, CA", "Jan 2023", "Present", [
                    "Served ranking models on Kubernetes at 3k requests per second with p99 under 40 ms.",
                    "Built an MLflow-based training pipeline used by 4 teams."]),
                ("Litware", "ML Engineer", "Remote", "Aug 2021", "Dec 2022", [
                    "Fine-tuned PyTorch NLP models for support ticket routing."]),
            ],
            [("Bayview Institute of Technology", "M.S.", "Computer Science", "2019", "2021")],
        ),
        "preferences": {
            "target_roles": ["Machine Learning Engineer", "ML Platform Engineer"], "seniority": ["mid", "senior"],
            "locations": ["San Francisco Bay Area", "San Jose", "Remote"], "work_modes": ["onsite", "hybrid", "remote"],
            "employment_types": ["full_time", "contract"], "min_salary": 150000, "exclude_new_grad_only": True,
            "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False,
                                   "needs_sponsorship_future": True},
        },
        "facts": [("start_date", "When can you start?", "Two weeks after an offer")],
    },
}  # fmt: skip


# ---------- JD 组装 ----------

SPONSOR_YES = "We sponsor H-1B visas and green cards for this role."
SPONSOR_NO = "We are unable to sponsor visas now or in the future for this position."
NEW_GRAD = "This role is only open to new graduates from the class of 2026."
CITIZEN = "Candidates must be U.S. citizens due to federal contract requirements."


@dataclass
class Case:
    id: str
    persona: str
    title: str
    company: str
    location: str
    work_mode: str  # onsite / hybrid / remote
    employment: str  # full_time / contract / ...
    stack: list[str]
    duties: list[str]
    salary: tuple[int, int] | None = None
    policy: str | None = None  # SPONSOR_YES / SPONSOR_NO / None
    extras: list[str] = field(default_factory=list)  # NEW_GRAD / CITIZEN 等
    expected_exclusions: list[str] = field(default_factory=list)
    expected: str = "maybe"
    why: str = ""

    @property
    def jd_text(self) -> str:
        emp = {"full_time": "Full-time", "contract": "Contract (12 months)", "contract_to_hire": "Contract-to-hire"}[
            self.employment
        ]
        lines = [
            f"{self.title} - {self.company}",
            f"Location: {self.location} ({self.work_mode.capitalize()})",
            f"Employment type: {emp}",
        ]
        if self.salary:
            lines.append(f"Salary range: ${self.salary[0]:,} - ${self.salary[1]:,} per year.")
        lines += ["", "What you'll do", *[f"- {d}" for d in self.duties], "", "What we're looking for"]
        lines += [f"- Experience with {s}" for s in self.stack]
        lines += [""] + [x for x in self.extras]
        if self.policy:
            lines.append(self.policy)
        lines.append(f"{self.company} is an equal opportunity employer.")
        return "\n".join(lines)

    @property
    def gold(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "company": self.company,
            "location_text": self.location,
            "work_mode": self.work_mode,
            "employment_type": self.employment,
            "salary_min": self.salary[0] if self.salary else None,
            "salary_max": self.salary[1] if self.salary else None,
            "salary_period": "year" if self.salary else "unknown",
            "sponsorship_policy": {SPONSOR_YES: "explicit_yes", SPONSOR_NO: "explicit_no"}.get(
                self.policy or "", "unclear"
            ),
            "sponsorship_evidence": self.policy or "",
            "new_grad_only": NEW_GRAD in self.extras,
            "new_grad_evidence": NEW_GRAD if NEW_GRAD in self.extras else "",
            "citizenship_required": CITIZEN in self.extras,
            "citizenship_evidence": CITIZEN if CITIZEN in self.extras else "",
        }


WEB = [
    "Build Python and FastAPI services",
    "Ship React and TypeScript features end to end",
    "Own PostgreSQL data models",
]
DATA = ["Build Airflow pipelines", "Model data in dbt and Snowflake", "Tune Spark jobs"]
IOS = ["Build features in Swift and SwiftUI", "Improve app performance and crash rates", "Mentor iOS engineers"]
JAVA = ["Build Spring Boot microservices", "Write JUnit tests", "Work with MySQL"]
ML = ["Train and deploy PyTorch models", "Run model serving on Kubernetes", "Build MLflow pipelines"]
EMBEDDED = ["Write C++ firmware for flight controllers", "Debug RTOS timing issues", "Bring up new hardware boards"]

CASES: list[Case] = [
    # ---- jordan：全端 Python/React，LA，未来需要 sponsorship，最低 10 万 ----
    Case("j1", "jordan", "Full Stack Engineer", "Harbor Labs", "Los Angeles, CA", "hybrid", "full_time",
         ["Python", "React", "TypeScript", "PostgreSQL"], WEB, (140000, 170000), None, expected="apply",
         why="技术栈几乎完全重合、地点第一优先、薪资够；sponsorship 没写只是不明"),
    Case("j2", "jordan", "Senior Backend Engineer", "Quarry Cloud", "Remote - US", "remote", "full_time",
         ["Python", "FastAPI", "PostgreSQL", "AWS"], WEB[:1] + WEB[2:], (150000, 185000), SPONSOR_YES, expected="apply",
         why="后端 Python 相符、remote 是第二优先、写明会 sponsor"),
    Case("j3", "jordan", "Full Stack Engineer", "Mesa Health", "Los Angeles, CA", "onsite", "full_time",
         ["Python", "React", "PostgreSQL"], WEB, (130000, 160000), SPONSOR_NO,
         expected_exclusions=["explicit_no_sponsorship"], expected="skip", why="未来需要 sponsorship，JD 写明不提供"),
    Case("j4", "jordan", "Embedded Software Engineer", "Skyward Drones", "Los Angeles, CA", "onsite", "full_time",
         ["C++", "RTOS", "embedded Linux"], EMBEDDED, (130000, 160000), None, expected="skip",
         why="嵌入式 C++，技术栈不相符"),
    Case("j5", "jordan", "Software Engineer, Platform", "Ledgerly", "Remote - US", "remote", "full_time",
         ["Go", "Kubernetes", "PostgreSQL", "React"], ["Build Go services", "Run Kubernetes clusters", "Own PostgreSQL"],
         (130000, 160000), None, expected="maybe", why="PostgreSQL、React 相符，但主要是 Go 与 Kubernetes"),
    Case("j6", "jordan", "Full Stack Developer", "Brightpath Staffing", "Los Angeles, CA", "remote", "contract",
         ["Python", "React"], WEB, None, None, expected_exclusions=["employment_type"], expected="skip",
         why="contract，求职者只接受全职"),
    Case("j7", "jordan", "Backend Engineer", "Tidewater Apps", "Los Angeles, CA", "hybrid", "full_time",
         ["Python", "Django", "PostgreSQL"], WEB, (70000, 90000), None,
         expected_exclusions=["salary_below_minimum"], expected="skip", why="薪资区间整个低于 10 万"),
    Case("j8", "jordan", "Software Engineer, New Grad", "Sunset Fintech", "Los Angeles, CA", "onsite", "full_time",
         ["Python", "React"], WEB, (110000, 130000), None, extras=[NEW_GRAD],
         expected_exclusions=["new_grad_only"], expected="skip", why="明确只收 2026 年毕业生"),
    # ---- sam：数据工程，remote 优先，现在就需要 sponsorship，最低 11 万 ----
    Case("s1", "sam", "Data Engineer", "Prairie Analytics", "Remote - US", "remote", "full_time",
         ["Python", "Airflow", "dbt", "Snowflake"], DATA, (130000, 155000), None, expected="apply",
         why="技术栈完全相符、remote"),
    Case("s2", "sam", "Senior Data Engineer", "Lakefront Bank", "Chicago, IL", "hybrid", "full_time",
         ["Spark", "Kafka", "AWS", "Python"], DATA, (150000, 180000), SPONSOR_YES, expected="apply",
         why="Spark、Kafka、AWS 相符，芝加哥 hybrid，写明 sponsor"),
    Case("s3", "sam", "Data Engineer", "Granite Insurance", "Remote - US", "remote", "full_time",
         ["Airflow", "SQL", "Snowflake"], DATA, (125000, 145000), SPONSOR_NO,
         expected_exclusions=["explicit_no_sponsorship"], expected="skip", why="现在就需要 sponsorship，JD 不提供"),
    Case("s4", "sam", "Frontend Engineer", "Pixel Forge", "Remote - US", "remote", "full_time",
         ["React", "CSS", "Figma"], ["Build React components", "Own the design system"], (120000, 140000), None,
         expected="skip", why="前端工作，不是数据工程"),
    Case("s5", "sam", "Analytics Engineer", "Crescent Media", "Chicago, IL", "hybrid", "full_time",
         ["SQL", "dbt", "Looker"], ["Model data in dbt", "Build Looker dashboards"], (115000, 135000), None,
         expected="maybe", why="dbt 与 SQL 相符，但偏 BI，少了 pipeline 工作"),
    Case("s6", "sam", "Data Engineer", "Apex Consulting", "Remote - US", "remote", "contract_to_hire",
         ["Python", "Airflow"], DATA, None, None, expected_exclusions=["employment_type"], expected="skip",
         why="contract-to-hire，只接受全职"),
    Case("s7", "sam", "Data Engineer", "Maple Logistics", "Chicago, IL", "onsite", "full_time",
         ["Python", "Spark", "SQL"], DATA, (80000, 100000), None, expected_exclusions=["salary_below_minimum"],
         expected="skip", why="薪资区间整个低于 11 万"),
    Case("s8", "sam", "Data Engineer", "Federal Data Partners", "Remote - US", "remote", "full_time",
         ["Python", "Airflow", "AWS"], DATA, (130000, 150000), None, extras=[CITIZEN],
         expected_exclusions=["citizenship_required"], expected="skip", why="要求美国公民，求职者需要 sponsorship"),
    # ---- mei：资深 iOS，西雅图 / remote，不需要 sponsorship，最低 14 万 ----
    Case("m1", "mei", "Senior iOS Engineer", "Evergreen Bank", "Seattle, WA", "hybrid", "full_time",
         ["Swift", "SwiftUI", "UIKit"], IOS, (170000, 210000), None, expected="apply", why="完全相符"),
    Case("m2", "mei", "Staff Mobile Engineer", "Orbit Travel", "Remote - US", "remote", "full_time",
         ["Swift", "Kotlin", "mobile architecture"], IOS, (190000, 230000), SPONSOR_NO, expected="apply",
         why="不需要 sponsorship，所以写明不 sponsor 不影响"),
    Case("m3", "mei", "Senior iOS Engineer", "Defense Mobile Systems", "Seattle, WA", "onsite", "full_time",
         ["Swift", "UIKit"], IOS, (160000, 190000), None, extras=[CITIZEN], expected="maybe",
         why="已可在美工作且不需要 sponsorship，公民要求不触发排除；onsite 不在接受的工作方式内"),
    Case("m4", "mei", "Backend Engineer", "Rainier Cloud", "Seattle, WA", "hybrid", "full_time",
         ["Go", "gRPC", "PostgreSQL"], ["Build Go services", "Design gRPC APIs"], (160000, 190000), None,
         expected="skip", why="后端 Go，不是 iOS"),
    Case("m5", "mei", "Senior Android Engineer", "Puget Games", "Remote - US", "remote", "full_time",
         ["Kotlin", "Jetpack Compose"], ["Build Android features in Kotlin"], (160000, 190000), None,
         expected="maybe", why="行动开发、懂一些 Kotlin，但主要经验是 iOS"),
    Case("m6", "mei", "iOS Developer", "Northshore Agency", "Remote - US", "remote", "contract",
         ["Swift", "SwiftUI"], IOS, None, None, expected_exclusions=["employment_type"], expected="skip",
         why="contract，只接受全职"),
    Case("m7", "mei", "iOS Engineer", "Cedar Startups", "Seattle, WA", "hybrid", "full_time",
         ["Swift", "SwiftUI"], IOS, (100000, 130000), None, expected_exclusions=["salary_below_minimum"],
         expected="skip", why="薪资整个低于 14 万"),
    Case("m8", "mei", "Senior iOS Engineer", "Harbor Health", "Seattle, WA", "hybrid", "full_time",
         ["Swift", "Core Data", "XCTest"], IOS, (130000, 175000), None, expected="apply",
         why="区间下段低于 14 万但上段涵盖，保留并标注；技术完全相符"),
    # ---- alex：初阶 Java 后端，纽约，可接受 New Grad，未来需要 sponsorship ----
    Case("a1", "alex", "Software Engineer I, Backend", "Empire Payments", "New York, NY", "hybrid", "full_time",
         ["Java", "Spring Boot", "MySQL"], JAVA, (110000, 130000), None, expected="apply", why="完全相符"),
    Case("a2", "alex", "Associate Software Engineer", "Liberty Health", "Jersey City, NJ", "onsite", "full_time",
         ["Java", "Spring", "SQL"], JAVA, (95000, 115000), SPONSOR_YES, expected="apply",
         why="初阶 Java、新泽西、写明 sponsor"),
    Case("a3", "alex", "Backend Engineer", "Hudson Retail", "New York, NY", "hybrid", "full_time",
         ["Java", "Spring Boot"], JAVA, (100000, 120000), SPONSOR_NO,
         expected_exclusions=["explicit_no_sponsorship"], expected="skip", why="未来需要 sponsorship，JD 不提供"),
    Case("a4", "alex", "Staff Distributed Systems Engineer", "Atlas Trading", "New York, NY", "onsite", "full_time",
         ["C++", "low-latency systems", "10+ years"], ["Design low-latency trading systems in C++"],
         (250000, 350000), None, expected="skip", why="Staff 级 C++ 低延迟，年资与技术都不符"),
    Case("a5", "alex", "Software Engineer, New Grad", "Brooklyn Robotics", "New York, NY", "onsite", "full_time",
         ["Java", "Python"], JAVA, (100000, 120000), None, extras=[NEW_GRAD], expected="apply",
         why="求职者没有排除 New Grad 职位，技术相符"),
    Case("a6", "alex", "Python Backend Engineer", "Gotham Data", "Remote - US", "remote", "full_time",
         ["Python", "Django", "PostgreSQL"], ["Build Django services", "Own PostgreSQL schemas"], (90000, 110000), None,
         expected="maybe", why="后端初阶相符，但是 Python 不是 Java"),
    Case("a7", "alex", "Java Developer", "Metro IT Services", "New York, NY", "onsite", "contract",
         ["Java", "Spring"], JAVA, None, None, expected_exclusions=["employment_type"], expected="skip",
         why="contract，只接受全职"),
    Case("a8", "alex", "Junior Backend Engineer", "Queens Logistics", "New York, NY", "onsite", "full_time",
         ["Java", "MySQL"], JAVA, (55000, 70000), None, expected_exclusions=["salary_below_minimum"],
         expected="skip", why="薪资整个低于 8 万"),
    # ---- chris：ML 工程，湾区，未来需要 sponsorship，可接受 contract，最低 15 万 ----
    Case("c1", "chris", "Machine Learning Engineer", "Redwood AI", "San Jose, CA", "hybrid", "full_time",
         ["PyTorch", "Kubernetes", "MLflow"], ML, (180000, 230000), None, expected="apply", why="完全相符"),
    Case("c2", "chris", "Senior ML Platform Engineer", "Bayline Search", "Remote - US", "remote", "full_time",
         ["Ray", "Kubernetes", "Python"], ML, (200000, 250000), SPONSOR_YES, expected="apply", why="相符且写明 sponsor"),
    Case("c3", "chris", "Machine Learning Engineer", "Golden Gate Health", "San Francisco, CA", "onsite", "full_time",
         ["PyTorch", "Python"], ML, (170000, 210000), SPONSOR_NO,
         expected_exclusions=["explicit_no_sponsorship"], expected="skip", why="未来需要 sponsorship，JD 不提供"),
    Case("c4", "chris", "Embedded Firmware Engineer", "Valley Sensors", "San Jose, CA", "onsite", "full_time",
         ["C", "C++", "RTOS"], EMBEDDED, (160000, 190000), None, expected="skip", why="嵌入式韧体，不相符"),
    Case("c5", "chris", "Data Scientist", "Mission Retail", "San Francisco, CA", "hybrid", "full_time",
         ["Python", "SQL", "A/B testing", "statistics"], ["Design A/B tests", "Build forecasting models"],
         (160000, 190000), None, expected="maybe", why="Python、建模相关，但偏统计分析而非 ML 工程"),
    Case("c6", "chris", "ML Engineer (Contract)", "Peninsula Partners", "Remote - US", "remote", "contract",
         ["PyTorch", "Kubernetes"], ML, None, None, expected="apply",
         why="求职者接受 contract，技术完全相符；薪资未列出只标注"),
    Case("c7", "chris", "Machine Learning Engineer", "Sunnyvale Startups", "San Jose, CA", "onsite", "full_time",
         ["PyTorch", "Python"], ML, (110000, 140000), None, expected_exclusions=["salary_below_minimum"],
         expected="skip", why="薪资整个低于 15 万"),
    Case("c8", "chris", "ML Engineer, New Grad", "Coastal Vision", "San Francisco, CA", "onsite", "full_time",
         ["PyTorch"], ML, (160000, 180000), None, extras=[NEW_GRAD], expected_exclusions=["new_grad_only"],
         expected="skip", why="明确只收 2026 年毕业生"),
]  # fmt: skip


# ---------- 雇主名称比对（程序正规化） ----------

# (a, b, 应该视为同一家)
ENTITY_PAIRS: list[tuple[str, str, bool]] = [
    ("Harbor Labs, Inc.", "HARBOR LABS INC", True),
    ("Harbor Labs Inc", "Harbor Labs", True),
    ("Quarry Cloud LLC", "Quarry Cloud, L.L.C.", True),
    ("Mesa Health Corporation", "Mesa Health Corp.", True),
    ("Ledgerly Holdings", "Ledgerly", True),
    ("The Tidewater Company", "Tidewater Co", True),
    ("Prairie Analytics Ltd.", "Prairie Analytics Limited", True),
    ("Lakefront Bank, N.A. d/b/a Lakefront", "Lakefront Bank NA", True),
    ("Granite Insurance Group LLC", "granite insurance group", True),
    ("Pixel Forge, PBC", "Pixel Forge", True),
    ("Crescent Media & Co.", "Crescent Media", True),
    ("Apex Consulting LLP", "Apex Consulting", True),
    ("Maple Logistics Incorporated", "Maple Logistics", True),
    ("Evergreen Bank, Inc. doing business as Evergreen", "Evergreen Bank", True),
    ("Orbit Travel GmbH", "Orbit Travel", True),
    ("Rainier Cloud, Inc", "Rainier Cloud Inc.", True),
    ("Puget Games L.L.C.", "Puget Games LLC", True),
    ("Cedar Startups, Inc.", "CEDAR STARTUPS", True),
    ("Harbor Health PLLC", "Harbor Health", True),
    ("Empire Payments Corp", "Empire Payments Corporation", True),
    ("Liberty Health, LP", "Liberty Health", True),
    ("Hudson Retail Co.", "Hudson Retail Company", True),
    ("Atlas Trading, LLC", "Atlas Trading", True),
    ("Brooklyn Robotics Inc", "Brooklyn Robotics, Inc.", True),
    ("Gotham Data Ltd", "Gotham Data", True),
    ("Queens Logistics, Inc.", "Queens Logistics", True),
    ("Redwood AI, Inc.", "Redwood AI", True),
    ("Bayline Search ULC", "Bayline Search", True),
    ("Golden Gate Health PC", "Golden Gate Health", True),
    ("Valley Sensors Holdings, Inc.", "Valley Sensors", True),
    ("Mission Retail S.A.", "Mission Retail", True),
    ("Peninsula Partners AG", "Peninsula Partners", True),
    ("Sunnyvale Startups B.V.", "Sunnyvale Startups", True),
    ("Coastal Vision, Inc", "coastal vision", True),
    ("Skyward Drones, Inc.", "Skyward  Drones   Inc", True),
    ("Harbor Labs", "Harbor Health", False),
    ("Quarry Cloud", "Quarry Capital", False),
    ("Mesa Health", "Mesa Healthcare Partners", False),
    ("Prairie Analytics", "Prairie Analytics Europe", False),
    ("Lakefront Bank", "Lakefront Capital", False),
    ("Pixel Forge", "Pixel Foundry", False),
    ("Apex Consulting", "Apex Consulting Group of Texas", False),
    ("Evergreen Bank", "Evergreen Bancorp", False),
    ("Orbit Travel", "Orbital Travel", False),
    ("Empire Payments", "Empire State Payments", False),
    ("Atlas Trading", "Atlas Traders", False),
    ("Redwood AI", "Redwood Analytics", False),
    ("Golden Gate Health", "Golden Gate Hospital", False),
    ("Valley Sensors", "Valley Sensor Systems", False),
    ("Coastal Vision", "Coastal Visions Media", False),
]
