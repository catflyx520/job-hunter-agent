"""写法学习 eval 的合成样本：三份 cover letter（原稿 → 用户修改版）。

三份修改都做同样三件事：删掉开头客套句、缩短到一半左右、结尾改成说明可以随时聊；
同时各自加进一个具体事实。规则里不该出现这些事实（STYLE_FORBIDDEN）。
人名、公司名全部虚构。
"""

from __future__ import annotations

from app.materials.style import Sample

STYLE_SAMPLES: list[Sample] = [
    Sample(
        question="",
        draft=(
            "Dear Hiring Manager,\n\n"
            "I hope this message finds you well. I am writing to express my sincere and enthusiastic interest in the "
            "Backend Engineer position at Harbor Labs. With a strong foundation in software engineering and a deep "
            "passion for building reliable systems, I believe I would be a valuable addition to your team.\n\n"
            "In my previous role, I worked on backend services that supported many users and collaborated closely "
            "with cross-functional teams to deliver high-quality software. I am a quick learner who thrives in "
            "fast-paced environments, and I take great pride in writing clean, maintainable code. I am also "
            "comfortable working with databases, APIs and cloud infrastructure, and I enjoy mentoring teammates and "
            "improving engineering practices.\n\n"
            "I am particularly drawn to Harbor Labs because of its commitment to innovation and its collaborative "
            "culture. I am confident that my skills and experience align well with the requirements of this role, "
            "and I am eager to contribute to your continued success.\n\n"
            "Thank you very much for taking the time to consider my application. I look forward to the opportunity "
            "to discuss how I can contribute to your team. I can start [NEEDS CONFIRMATION: start date].\n\n"
            "Sincerely,\nMina Alder"
        ),
        final=(
            "I'm applying for the Backend Engineer role at Harbor Labs. At my last job I rebuilt an event pipeline "
            "on Kafka that cut report delays from hours to minutes, and I like working close to the data and the "
            "people who use it.\n\n"
            "I'd be glad to talk about how that fits what your team is building. Happy to chat any time.\n\n"
            "Mina Alder"
        ),
    ),
    Sample(
        question="",
        draft=(
            "Dear Hiring Team,\n\n"
            "I hope you are doing well. I am excited to submit my application for the Platform Engineer opening at "
            "Quarry Cloud. As a dedicated and results-driven engineer with a passion for developer tooling, I am "
            "confident that my background makes me an excellent fit for this opportunity.\n\n"
            "Throughout my career, I have helped teams ship software faster and more safely. I have experience "
            "improving deployment workflows, monitoring production systems, and partnering with product managers "
            "and designers to prioritize work. I am a strong communicator who values transparency, and I always "
            "strive to leave systems better than I found them.\n\n"
            "Quarry Cloud's mission resonates deeply with me, and I would be thrilled to bring my enthusiasm and "
            "technical skills to your organization. I believe that my proactive attitude and eagerness to learn "
            "would allow me to make a meaningful impact from day one.\n\n"
            "I truly appreciate your time and consideration, and I would welcome the chance to speak with you "
            "further about this exciting position.\n\n"
            "Best regards,\nTomas Verell"
        ),
        final=(
            "I'm applying for the Platform Engineer role at Quarry Cloud. I moved our deploys to Terraform and "
            "brought rollback time under a minute, and I'd like to do the same kind of work for your developers.\n\n"
            "Glad to talk whenever suits you.\n\n"
            "Tomas Verell"
        ),
    ),
    Sample(
        question="",
        draft=(
            "Dear Sir or Madam,\n\n"
            "I trust this letter finds you in good health. I would like to express my great enthusiasm for the Data "
            "Engineer position at Lumen Freight. I bring a solid track record of delivering data solutions, along "
            "with a genuine passion for turning raw information into actionable insights.\n\n"
            "Over the past several years, I have designed and maintained data pipelines, partnered with analysts to "
            "define metrics, and ensured the quality and availability of key datasets. I am a detail-oriented "
            "team player with excellent problem-solving skills, and I am always looking for ways to improve "
            "processes and drive efficiency across the organization.\n\n"
            "Lumen Freight's reputation for excellence and its focus on logistics innovation make it an ideal place "
            "for me to grow my career. I am certain that my dedication and adaptability would make me a strong "
            "contributor to your data organization.\n\n"
            "Thank you for your consideration. I eagerly await the opportunity to discuss my qualifications in "
            "greater detail.\n\n"
            "Respectfully,\nIsla Brandt"
        ),
        final=(
            "I'm applying for the Data Engineer role at Lumen Freight. I built the monitoring that took our "
            "pipeline uptime to 99.95 percent, and I enjoy making data dependable for the analysts relying on it.\n\n"
            "Happy to talk any time about how I could help.\n\n"
            "Isla Brandt"
        ),
    ),
]

# 样本里的具体事实：公司、技术、数字、人名。规则里出现任何一个就是把事实带进了每一份草稿。
STYLE_FORBIDDEN: list[str] = [
    # 这两个是被禁止的规则主题（占位符），不是泄漏的事实
    "placeholder",
    "needs confirmation",
    "Harbor Labs",
    "Quarry Cloud",
    "Lumen Freight",
    "Harbor",
    "Quarry",
    "Lumen",
    "Freight",
    "Backend Engineer",
    "Platform Engineer",
    "Data Engineer",
    "Kafka",
    "Terraform",
    "event pipeline",
    "report delays",
    "hours to minutes",
    "rollback",
    "pipeline uptime",
    "99.95",
    "99.9",
    "Mina",
    "Tomas",
    "Isla",
    "Alder",
    "Verell",
    "Brandt",
]
