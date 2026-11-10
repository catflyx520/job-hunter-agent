"""签证资料导入进度：build.py 写状态档，后端读出来给职位页显示。"""

import json
from datetime import UTC, datetime, timedelta

from app.sponsor.import_status import ImportProgress, read_status, status_path


def test_progress_round_trip(tmp_path):
    assert read_status(tmp_path) is None  # 从没跑过
    p = ImportProgress(tmp_path)
    p.update(stage="reading", file="LCA_Disclosure_Data_FY2025_Q1.xlsx", files_done=0, files_total=3)
    s = read_status(tmp_path)
    assert s["state"] == "running" and s["stage_label"] == "读取官方原始档" and s["files_total"] == 3
    p.finish("已导入 10 个雇主。")
    assert read_status(tmp_path)["state"] == "done"
    p.fail("坏档")
    assert read_status(tmp_path)["message"] == "坏档"


def test_running_without_updates_becomes_stale(tmp_path):
    ImportProgress(tmp_path).update(stage="importing")
    path = status_path(tmp_path)
    s = json.loads(path.read_text(encoding="utf-8"))
    s["updated_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    path.write_text(json.dumps(s), encoding="utf-8")
    assert read_status(tmp_path)["state"] == "stale"  # 程序被强制中断时来不及写结束
