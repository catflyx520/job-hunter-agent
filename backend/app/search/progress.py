"""搜索进度（只放在记忆体里，给页面显示用；服务重启后进行中的批次会标成失败）。"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_progress: dict[str, dict[str, Any]] = {}
_cancelled: set[str] = set()


def begin(run_id: str, site_ids: list[str]) -> None:
    with _lock:
        _progress[run_id] = {
            "phase": "searching",
            "sites": {s: "searching" for s in site_ids},
            "found": {},
            "total": 0,
            "done": 0,
            "outcomes": {},
        }


def site_done(run_id: str, site_id: str, status: str, found: int) -> None:
    with _lock:
        p = _progress.get(run_id)
        if p:
            p["sites"][site_id] = status
            p["found"][site_id] = found


def start_processing(run_id: str, total: int) -> None:
    with _lock:
        p = _progress.get(run_id)
        if p:
            p["phase"], p["total"] = "processing", total


def lead_done(run_id: str, outcome: str) -> None:
    with _lock:
        p = _progress.get(run_id)
        if p:
            p["done"] += 1
            p["outcomes"][outcome] = p["outcomes"].get(outcome, 0) + 1


def finish(run_id: str) -> None:
    with _lock:
        _progress.pop(run_id, None)
        _cancelled.discard(run_id)


def snapshot(run_id: str) -> dict[str, Any] | None:
    with _lock:
        p = _progress.get(run_id)
        if p is None:
            return None
        return {**p, "sites": dict(p["sites"]), "found": dict(p["found"]), "outcomes": dict(p["outcomes"])}


def cancel(run_id: str) -> None:
    with _lock:
        _cancelled.add(run_id)


def is_cancelled(run_id: str) -> bool:
    with _lock:
        return run_id in _cancelled


def active() -> list[str]:
    with _lock:
        return list(_progress)
