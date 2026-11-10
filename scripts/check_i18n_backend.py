"""列出后端 tr("...") 用到、但 app/core/i18n_en.py 没有英文的句子。

用法（在 backend/）：uv run python ../scripts/check_i18n_backend.py [--json]
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.i18n_en import EN  # noqa: E402

CJK = re.compile(r"[一-鿿]")


def keys() -> set[str]:
    out = set()
    for path in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and CJK.search(node.args[0].value)
            ):
                out.add(node.args[0].value)
    return out


def main() -> int:
    used = keys()
    missing = sorted(k for k in used if k not in EN)
    if "--json" in sys.argv:
        print(json.dumps(missing, ensure_ascii=False, indent=1))
    else:
        for k in missing:
            print(k)
        print(f"\n{len(used)} 个句子，缺 {len(missing)} 个英文翻译。")
    # 英文里的 {name} 必须和中文一致，否则 format 会出错
    bad = [k for k in used if k in EN and set(re.findall(r"\{(\w+)\}", k)) != set(re.findall(r"\{(\w+)\}", EN[k]))]
    for k in bad:
        print(f"变数不一致：{k}")
    return 1 if missing or bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
