"""签证资料导入进度：build.py 是独立程序，把进度写进 data/sponsor/import_status.json，后端读来给页面显示。

状态档只有进度数字，没有任何资料内容。程序被强制中断时来不及写「结束」，所以超过 STALE_AFTER 没更新就当成中断。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

STALE_AFTER = timedelta(minutes=20)  # 最慢的一步（读 250 MB 的 xlsx）也会在这之内更新一次

STAGES = {
    "reading": "读取官方原始档",
    "summarizing": "写出汇总档",
    "importing": "写入数据库",
    "recomputing": "重算职位公司的签证状态",
}


def status_path(data_dir: Path) -> Path:
    return data_dir / "sponsor" / "import_status.json"


class ImportProgress:
    """build.py 用：每一步呼叫 update()，结束时 finish() 或 fail()。"""

    def __init__(self, data_dir: Path) -> None:
        self.path = status_path(data_dir)
        self.state: dict = {"state": "running", "started_at": _now()}

    def update(self, **fields) -> None:
        self.state.update(fields)
        self._write()

    def finish(self, message: str) -> None:
        self.update(state="done", message=message, finished_at=_now())

    def fail(self, message: str) -> None:
        self.update(state="failed", message=message, finished_at=_now())

    def _write(self) -> None:
        self.state["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # 原子替换，后端不会读到写一半的档


def read_status(data_dir: Path) -> dict | None:
    """回传最近一次导入的状态；从没跑过回传 None。执行中但太久没更新的标成 stale。"""
    path = status_path(data_dir)
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if s.get("state") == "running":
        try:
            updated = datetime.fromisoformat(s["updated_at"])
        except (KeyError, ValueError):
            updated = None
        if updated is None or datetime.now(UTC) - updated > STALE_AFTER:
            s["state"] = "stale"
    s["stage_label"] = STAGES.get(s.get("stage", ""), "")
    return s


def _now() -> str:
    return datetime.now(UTC).isoformat()
