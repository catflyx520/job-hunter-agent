"""产生合成测试履历（虚构人物）到 evals/datasets/resumes/。

cd backend && uv run python ../evals/datasets/make_synthetic_resumes.py
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from tests.samples import make_docx, make_pdf  # noqa: E402

out = Path(__file__).resolve().parent / "resumes"
out.mkdir(exist_ok=True)
(out / "jordan-rivera.pdf").write_bytes(make_pdf())
(out / "jordan-rivera.docx").write_bytes(make_docx())
(out / "jordan-rivera-table.docx").write_bytes(make_docx(with_table=True))
print(f"已写入 {out}")
