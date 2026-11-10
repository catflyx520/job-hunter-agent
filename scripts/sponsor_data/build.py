"""汇总 data/sponsor/raw/ 里的官方原始档，输出汇总档并（可选）导入数据库。

用法（在 backend/ 目录）：
    uv run python ../scripts/sponsor_data/build.py                  # 汇总并导入数据库
    uv run python ../scripts/sponsor_data/build.py --no-import      # 只产生汇总档（例如要发布到 GitHub Releases）
    uv run python ../scripts/sponsor_data/build.py --import-only data/sponsor/summary.jsonl.gz

汇总档：data/sponsor/summary.jsonl.gz（第一行是 manifest：每个原始档的网址、SHA-256、列数）。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.core.db import get_sessionmaker  # noqa: E402
from app.sponsor.import_status import ImportProgress  # noqa: E402
from app.sponsor.lookup import recompute_all_statuses  # noqa: E402
from app.sponsor.pipeline import PipelineError, aggregate, identify, import_summary, write_summary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-import", action="store_true", help="只产生汇总档，不写入数据库")
    parser.add_argument("--import-only", type=Path, help="直接导入已有的汇总档")
    args = parser.parse_args()

    data = get_settings().data_dir / "sponsor"
    summary = args.import_only or data / "summary.jsonl.gz"
    # 进度写进 data/sponsor/import_status.json，职位页会显示「导入中」
    prog = ImportProgress(get_settings().data_dir)
    prog.update(stage="reading")
    try:
        if not args.import_only:
            raw = data / "raw"
            files = [sf for p in sorted(raw.glob("*")) if (sf := identify(p))]
            ignored = [p.name for p in sorted(raw.glob("*")) if p.is_file() and not identify(p)]
            if ignored:
                print(f"略过无法辨识的档案（请保留官方档名）：{', '.join(ignored)}")
            if not files:
                print(f"{raw} 里没有官方资料档。请先执行 download.py，或手动下载后放进这个资料夹。")
                return 1
            t0 = time.time()
            employers, rows_read = aggregate(files, progress=prog.update)
            prog.update(stage="summarizing", files_done=len(files), files_total=len(files))
            write_summary(employers, files, rows_read, summary)
            print(f"汇总完成：{len(employers)} 个雇主，{time.time() - t0:.0f} 秒 → {summary}")
        if args.no_import:
            prog.finish("已产生汇总档（没有导入数据库）。")
            return 0
        with get_sessionmaker()() as db:
            prog.update(stage="importing", employers_done=0)
            result = import_summary(db, summary, progress=prog.update)
            prog.update(stage="recomputing")
            updated = recompute_all_statuses(db)
            db.commit()
        msg = f"已导入 {result['employers']} 个雇主、{result['datasets']} 个资料档；重算 {updated} 家公司的签证状态。"
        prog.finish(msg)
        print(msg)
    except PipelineError as exc:
        prog.fail(str(exc))
        print(f"错误：{exc}")
        return 2
    except BaseException as exc:  # 包括 Ctrl+C：让页面知道导入没完成
        prog.fail(f"导入中断：{type(exc).__name__}")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
