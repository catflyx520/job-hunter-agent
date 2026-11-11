"""把目前启用的履历导出给 demo，去掉邮箱和电话。

用法（在 backend/）：
    uv run python ../scripts/export_demo_resume.py

输出 frontend/public/demo-resume.json（已在 .gitignore），只跟着 demo 版本部署，不进 git。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import get_sessionmaker  # noqa: E402
from app.models import Resume  # noqa: E402

OUT = ROOT / "frontend" / "public" / "demo-resume.json"
CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.\w+|\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")


def public_resume(parsed: dict) -> dict:
    """清掉联系方式；正文里还藏着邮箱或电话就报错，不写出档案。"""
    out = {**parsed, "basics": {**parsed["basics"], "email": "", "phone": ""}}
    if CONTACT.search(json.dumps(out, ensure_ascii=False)):
        raise ValueError("履历正文里还有邮箱或电话，请先在「履历内容」删掉再导出")
    return out


def main() -> None:
    with get_sessionmaker()() as db:
        resume = db.scalar(select(Resume).where(Resume.is_active))
    if resume is None:
        raise SystemExit("没有启用中的履历")
    OUT.write_text(json.dumps(public_resume(resume.parsed), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT.name}")


if __name__ == "__main__":
    main()
