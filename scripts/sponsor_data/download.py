"""下载官方签证资料原始档到 data/sponsor/raw/。

用法（在 backend/ 目录）：
    uv run python ../scripts/sponsor_data/download.py                 # 预设：最近 3 个财年
    uv run python ../scripts/sponsor_data/download.py --years 2024 2025

官方网站（dol.gov、uscis.gov）有防爬保护，程序下载常被拒绝（HTTP 403）。本工具不绕过保护：
被拒绝时会列出网址，请用浏览器手动下载，档名不要改，放进 data/sponsor/raw/ 后再执行 build.py。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.sponsor.pipeline import DOL_BASE, USCIS_BASE  # noqa: E402

PAGES = {
    "DOL OFLC 资料页（LCA / PERM）": "https://www.dol.gov/agencies/eta/foreign-labor/performance",
    "USCIS H-1B Employer Data Hub": "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub",
}


def latest_complete_fy(today: dt.date) -> int:
    """美国联邦财年 10/1 开始；官方 Q4 档通常在财年结束后约 2 个月发布。"""
    fy = today.year if today.month < 10 else today.year + 1
    return fy - 1 if today.month >= 12 or today.month < 10 else fy - 2


def file_urls(years: list[int]) -> list[str]:
    urls = []
    for y in years:
        urls.append(f"{DOL_BASE}LCA_Disclosure_Data_FY{y}_Q4.xlsx")
        urls.append(f"{DOL_BASE}PERM_Disclosure_Data_FY{y}_Q4.xlsx")
        urls.append(f"{USCIS_BASE}h1b_datahubexport-{y}.csv")
    return urls


def download(url: str, dest: Path) -> str:
    if dest.exists() and dest.stat().st_size > 0:
        return "已存在，略过"
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "job-hunter-agent/0.1 (sponsor data pipeline)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, part.open("wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        return f"失败：HTTP {exc.code}"
    except OSError as exc:
        part.unlink(missing_ok=True)
        return f"失败：{type(exc).__name__}"
    part.replace(dest)
    return f"完成（{dest.stat().st_size // 1024} KB）"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="*", help="财年，例如 2023 2024 2025")
    args = parser.parse_args()
    last = latest_complete_fy(dt.date.today())
    years = args.years or [last - 2, last - 1, last]

    raw = get_settings().data_dir / "sponsor" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    print(f"财年：{years}；存放位置：{raw}")
    failed = []
    for url in file_urls(years):
        name = url.rsplit("/", 1)[-1]
        result = download(url, raw / name)
        print(f"- {name}: {result}")
        if result.startswith("失败"):
            failed.append(url)
    if failed:
        print("\n以下档案无法自动下载（官方网站拒绝程序存取，本工具不绕过）。")
        print(f"请用浏览器打开网址下载，档名不要改，放进 {raw}：")
        for url in failed:
            print(f"  {url}")
        print("如果网址失效（官方有时会搬移档案），请到资料页找同名档案：")
        for label, url in PAGES.items():
            print(f"  {label}: {url}")
        print("USCIS 较新年份可能没有 h1b_datahubexport-YYYY.csv，可略过；LCA / PERM 是主要来源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
