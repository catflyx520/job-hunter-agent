"""Evals（SPEC 第 6 节）。

两组：
- program（预设，CI 跑）：不呼叫模型，检查硬性排除规则、JD 原句核对、雇主名称正规化、cover letter 真实性检查。
- llm（本机跑，用你自己的模型）：职位抽取准确率、排除的 precision / recall、建议等级准确率、
  cover letter 引用率、问答「需要确认」是否列对。

  cd backend
  uv run python ../evals/run_evals.py
  uv run python ../evals/run_evals.py --suite llm --provider claude_cli --model sonnet
  uv run python ../evals/run_evals.py --suite llm --provider anthropic --model claude-haiku-5-5   # 需要 ANTHROPIC_API_KEY

结果写到 evals/results/，并和 evals/thresholds.json 比较；低于门槛就以错误码 1 结束。
所有资料都是合成的（evals/datasets/cases.py）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 终端预设编码会把中文印成乱码
sys.path.insert(0, str(ROOT / "datasets"))

from cases import CASES, ENTITY_PAIRS, PERSONAS, Case  # noqa: E402

from app.graphs.materials import Citation, Draft, FactItem, NeedItem, generate_draft, verify_draft  # noqa: E402
from app.jobs.exclusion import check_exclusions  # noqa: E402
from app.jobs.extract import JobExtraction, extract_job, verify_evidence  # noqa: E402
from app.jobs.match import score_match  # noqa: E402
from app.jobs.normalize import location_tier, normalize_company  # noqa: E402
from app.models import Company, Job  # noqa: E402
from app.rag.chunks import make_chunks  # noqa: E402
from app.rag.retrieve import Evidence  # noqa: E402
from app.schemas.profile import JobPreferences  # noqa: E402
from app.schemas.resume import ParsedResume  # noqa: E402

LEVELS = ["skip", "maybe", "apply"]


# ---------- 共用 ----------


def prefs_of(persona: str) -> JobPreferences:
    return JobPreferences.model_validate(PERSONAS[persona]["preferences"])


def evidence_of(persona: str) -> list[Evidence]:
    parsed = ParsedResume.model_validate(PERSONAS[persona]["resume"])
    return [Evidence(f"ref:{c.source_ref}", c.source_ref, c.section, c.text) for c in make_chunks(parsed)]


def facts_of(persona: str) -> list[FactItem]:
    return [FactItem(k, q, v) for k, q, v in PERSONAS[persona]["facts"]]


def job_from(ex: dict[str, Any], jd_text: str, prefs: JobPreferences) -> Job:
    """不进数据库的职位物件，给排除规则与评分用。"""
    job = Job(
        title=ex["title"],
        location_text=ex.get("location_text") or None,
        work_mode=ex.get("work_mode", "unknown"),
        employment_type=ex.get("employment_type", "unknown"),
        salary_min=ex.get("salary_min"),
        salary_max=ex.get("salary_max"),
        salary_period=ex.get("salary_period") if (ex.get("salary_min") or ex.get("salary_max")) else None,
        sponsorship_policy=ex.get("sponsorship_policy", "unclear"),
        new_grad_only=ex.get("new_grad_only"),
        citizenship_required=ex.get("citizenship_required"),
        status="active",
        verification_source="pasted",
        jd_text=jd_text,
    )
    job.company = Company(display_name=ex.get("company") or "unknown", normalized_name="x")
    job.location_tier = location_tier(ex.get("location_text") or "", job.work_mode, prefs.locations)
    return job


def prf(pairs: list[tuple[set[str], set[str]]]) -> dict[str, float]:
    tp = sum(len(exp & got) for exp, got in pairs)
    fp = sum(len(got - exp) for exp, got in pairs)
    fn = sum(len(exp - got) for exp, got in pairs)
    return {
        "precision": round(tp / (tp + fp), 3) if tp + fp else 1.0,
        "recall": round(tp / (tp + fn), 3) if tp + fn else 1.0,
        "case_accuracy": round(sum(exp == got for exp, got in pairs) / len(pairs), 3) if pairs else 1.0,
    }


# ---------- program 组（不呼叫模型） ----------

FAKE_EVIDENCE = {
    "sponsorship_evidence": "We happily sponsor every visa type forever.",
    "new_grad_evidence": "Only students graduating this spring may apply.",
    "citizenship_evidence": "Applicants must hold U.S. citizenship.",
}


def program_exclusions(failures: list[str]) -> dict[str, float]:
    pairs = []
    for c in CASES:
        got = set(check_exclusions(job_from(c.gold, c.jd_text, prefs_of(c.persona)), prefs_of(c.persona)).reasons)
        exp = set(c.expected_exclusions)
        if got != exp:
            failures.append(f"排除规则 {c.id}：预期 {sorted(exp)}，实际 {sorted(got)}")
        pairs.append((exp, got))
    return prf(pairs)


def program_evidence_guard(failures: list[str]) -> dict[str, float]:
    """有原句的判断要保留；原句不在 JD 里就退回不明。"""
    ok = total = 0
    for c in CASES:
        gold = c.gold
        claims = [(f, e) for f, e in (("sponsorship_policy", "sponsorship_evidence"), ("new_grad_only", "new_grad_evidence"),
                  ("citizenship_required", "citizenship_evidence")) if gold[e]]  # fmt: skip
        for field, ev_field in claims:
            real = JobExtraction(**{**gold, "required_skills": []})
            verify_evidence(real, c.jd_text)
            kept = getattr(real, field) == gold[field]
            fake = JobExtraction(**{**gold, ev_field: FAKE_EVIDENCE[ev_field], "required_skills": []})
            verify_evidence(fake, c.jd_text)
            downgraded = getattr(fake, field) in ("unclear", False)
            total += 2
            ok += kept + downgraded
            if not kept:
                failures.append(f"原句核对 {c.id}.{field}：真实原句却被退回")
            if not downgraded:
                failures.append(f"原句核对 {c.id}.{field}：编造的原句没有被挡下")
    return {"accuracy": round(ok / total, 3) if total else 1.0, "checks": total}


def program_entities(failures: list[str]) -> dict[str, float]:
    ok = 0
    for a, b, same in ENTITY_PAIRS:
        got = normalize_company(a) == normalize_company(b)
        ok += got == same
        if got != same:
            failures.append(f"名称正规化：「{a}」vs「{b}」预期{'相同' if same else '不同'}")
    return {"accuracy": round(ok / len(ENTITY_PAIRS), 3), "pairs": len(ENTITY_PAIRS)}


def program_truth_check(failures: list[str]) -> dict[str, float]:
    ev = evidence_of("jordan")
    e0 = ev[1].id  # 第一段经历
    facts = facts_of("jordan")
    jd = CASES[0].jd_text
    fixtures = [
        ("全部有来源", Draft(text="I built a FastAPI service.", citations=[Citation(sentence="I built a FastAPI service.", evidence_ids=[e0])]), []),
        ("没有来源的句子", Draft(text="I founded a startup.", citations=[Citation(sentence="I founded a startup.")]), ["sentence"]),
        ("编造的数字", Draft(text="I managed 40 engineers.", citations=[Citation(sentence="I managed 40 engineers.", evidence_ids=[e0])]), ["number"]),
        ("不存在的证据编号", Draft(text="I led a team.", citations=[Citation(sentence="I led a team.", evidence_ids=["ref:nope"])]), ["sentence", "refs"]),
        ("占位符", Draft(text="I can start [NEEDS CONFIRMATION: start date].", citations=[]), ["placeholder"]),
        ("引用已确认事实", Draft(text="I need 2 weeks of notice.", citations=[Citation(sentence="I need 2 weeks of notice.", fact_keys=["notice_period"])]), []),
        ("JD 里的数字不算编造", Draft(text="The range of $140,000 works for me.", citations=[Citation(sentence="The range of $140,000 works for me.", evidence_ids=[e0])]), []),
        ("同一个数字换写法不算编造", Draft(text="It processes 2 million events, or 2,000,000 per day.", citations=[Citation(sentence="It processes 2 million events, or 2,000,000 per day.", evidence_ids=[e0])]), []),
        ("换写法后数值不同要抓出来", Draft(text="It processes 3 million events per day.", citations=[Citation(sentence="It processes 3 million events per day.", evidence_ids=[e0])]), ["number"]),
        ("模型自己列的需要确认", Draft(text="Hello.", citations=[], needs_confirmation=[NeedItem(item="salary", why="未提供")]), ["model"]),
    ]  # fmt: skip
    ok = 0
    for name, draft, expect in fixtures:
        _, needs, _ = verify_draft(draft, ev, facts, jd)
        items = " ".join(n["item"] for n in needs)
        got = []
        if "「" in items and any(n["why"].startswith("这句话") for n in needs):
            got.append("sentence")
        if any(n["item"].startswith("数字") for n in needs):
            got.append("number")
        if any(n["item"] == "引用" for n in needs):
            got.append("refs")
        if any(n["why"].startswith("草稿中留了占位符") for n in needs):
            got.append("placeholder")
        if any(n["item"] == "salary" for n in needs):
            got.append("model")
        if sorted(got) == sorted(expect):
            ok += 1
        else:
            failures.append(f"真实性检查「{name}」：预期 {expect}，实际 {got}")
    return {"accuracy": round(ok / len(fixtures), 3), "fixtures": len(fixtures)}


def run_program() -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    metrics = {
        "exclusion_rules": program_exclusions(failures),
        "evidence_guard": program_evidence_guard(failures),
        "entity_normalization": program_entities(failures),
        "truth_check": program_truth_check(failures),
    }
    return metrics, failures


# ---------- llm 组（用真实模型，本机跑） ----------


def build_provider(kind: str, model: str):
    from app.llm.api_providers import AnthropicProvider, OllamaProvider, OpenAIProvider
    from app.llm.cli_providers import ClaudeCliProvider, CodexCliProvider

    match kind:
        case "claude_cli":
            return ClaudeCliProvider(model)
        case "codex_cli":
            return CodexCliProvider(model)
        case "anthropic":
            return AnthropicProvider(model, os.environ["ANTHROPIC_API_KEY"])
        case "openai":
            return OpenAIProvider(model, os.environ["OPENAI_API_KEY"])
        case "ollama":
            return OllamaProvider(model, os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    raise SystemExit(f"不支援的 provider：{kind}")


EXTRACT_FIELDS = ["sponsorship_policy", "new_grad_only", "citizenship_required", "employment_type", "work_mode",
                  "salary_min", "salary_max"]  # fmt: skip


def eval_case(provider, c: Case) -> dict[str, Any]:
    prefs = prefs_of(c.persona)
    started = time.time()
    try:
        ex, _ = extract_job(provider, c.jd_text)
        extracted = ex.model_dump()
        job = job_from(extracted, c.jd_text, prefs)
        exclusion = check_exclusions(job, prefs)
        rec, score = "skip", None
        if not exclusion.excluded:
            m = score_match(provider, job, prefs, evidence_of(c.persona), exclusion)
            rec, score = m["recommendation"], m["score"]
        return {
            "id": c.id,
            "fields": {f: extracted.get(f) == c.gold[f] for f in EXTRACT_FIELDS},
            "extracted": {f: extracted.get(f) for f in EXTRACT_FIELDS},
            "exclusions": sorted(exclusion.reasons),
            "expected_exclusions": sorted(c.expected_exclusions),
            "recommendation": rec,
            "expected": c.expected,
            "score": score,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:  # noqa: BLE001  单一案例失败照样记录
        return {"id": c.id, "error": f"{type(exc).__name__}: {exc}"}


def eval_materials(provider, persona: str) -> dict[str, Any]:
    c = next(x for x in CASES if x.persona == persona)
    ev, facts = evidence_of(persona), facts_of(persona)
    out: dict[str, Any] = {"persona": persona}
    try:
        base = {"evidence": ev, "facts": facts, "jd_text": c.jd_text, "job_title": c.title, "company": c.company,
                "language": "en"}  # fmt: skip
        draft = generate_draft(provider, {**base, "kind": "cover_letter"})
        cits, needs, _ = verify_draft(draft, ev, facts, c.jd_text)
        out["cover_sentences"] = len(cits)
        out["cover_supported"] = sum(x["supported"] for x in cits)
        numbers = [n["item"] for n in needs if n["item"].startswith("数字")]
        out["cover_unsourced_numbers"] = len(numbers)
        out["cover_number_items"] = numbers  # 留下明细，指标不达标时才查得出原因
        out["cover_text"] = draft.text

        q = "What is your expected annual base salary?"
        draft = generate_draft(provider, {**base, "kind": "qa", "question": q})
        _, needs, _ = verify_draft(draft, ev, facts, c.jd_text + " " + q)
        out["qa_salary_flagged"] = bool(needs)  # 事实库没有薪资 → 一定要列「需要确认」

        q = "When can you start?"
        draft = generate_draft(provider, {**base, "kind": "qa", "question": q})
        _, needs, used = verify_draft(draft, ev, facts, c.jd_text + " " + q)
        # 事实库有开始日期或 notice period 就该引用它回答；两个都没有才该列「需要确认」
        relevant = {f.key for f in facts} & {"start_date", "notice_period"}
        out["qa_start_ok"] = bool(relevant & set(used)) if relevant else bool(needs)
        out["qa_start_text"], out["qa_start_needs"], out["qa_start_facts"] = draft.text, needs, used
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def ratio(part: float, whole: float) -> float | None:
    """分母是 0（全部失败或没跑）时回传 None：是「没有结果」，不是 0 分。"""
    return round(part / whole, 3) if whole else None


def run_llm(
    kind: str, model: str, limit: int | None, personas: list[str] | None, workers: int, resume: Path | None = None
):
    provider = build_provider(kind, model)
    cases = [c for c in CASES if not personas or c.persona in personas][: limit or None]
    names = sorted({c.persona for c in cases})
    # --resume：沿用上次已成功的结果，只重跑失败或没跑到的部分（省模型额度）
    old_cases: dict[str, dict] = {}
    old_mats: dict[str, dict] = {}
    if resume:
        prev = json.loads(resume.read_text(encoding="utf-8"))
        if (prev.get("provider"), prev.get("model")) != (kind, model):
            raise SystemExit(f"--resume 的结果来自 {prev.get('provider')} / {prev.get('model')}，和这次的模型不同。")
        old_cases = {r["id"]: r for r in prev.get("cases", []) if "error" not in r}
        old_mats = {m["persona"]: m for m in prev.get("materials", []) if "error" not in m}
        print(f"沿用上次结果：{len(old_cases)} 个案例、{len(old_mats)} 组材料")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        case_results = list(pool.map(lambda c: old_cases.get(c.id) or eval_case(provider, c), cases))
        mat_results = list(pool.map(lambda p: old_mats.get(p) or eval_materials(provider, p), names))
        for r in case_results:
            print(f"  {r['id']}: {r.get('error') or (r['recommendation'], r['expected'], r['exclusions'])}")

    good = [r for r in case_results if "error" not in r]
    failures = [f"{r['id']}：{r['error']}" for r in case_results if "error" in r]
    failures += [f"materials {m['persona']}：{m['error']}" for m in mat_results if "error" in m]
    field_acc = {f: ratio(sum(r["fields"][f] for r in good), len(good)) for f in EXTRACT_FIELDS}
    rec_exact = sum(r["recommendation"] == r["expected"] for r in good)
    rec_near = sum(abs(LEVELS.index(r["recommendation"]) - LEVELS.index(r["expected"])) <= 1 for r in good)
    mats = [m for m in mat_results if "error" not in m]
    sentences = sum(m["cover_sentences"] for m in mats)
    metrics = {
        "cases": {"total": len(cases), "ok": len(good)},
        "extraction": field_acc,
        "exclusions": prf([(set(r["expected_exclusions"]), set(r["exclusions"])) for r in good]) if good else None,
        "recommendation": {"exact": ratio(rec_exact, len(good)), "within_one": ratio(rec_near, len(good))},
        "materials": {
            "ok": len(mats),
            "total": len(names),
            "cover_supported_ratio": ratio(sum(m["cover_supported"] for m in mats), sentences),
            "cover_no_unsourced_numbers": ratio(sum(m["cover_unsourced_numbers"] == 0 for m in mats), len(mats)),
            "qa_salary_flagged": ratio(sum(m["qa_salary_flagged"] for m in mats), len(mats)),
            "qa_start_ok": ratio(sum(m["qa_start_ok"] for m in mats), len(mats)),
        },
    }
    for r in good:
        if r["exclusions"] != r["expected_exclusions"]:
            failures.append(
                f"{r['id']} 排除：预期 {r['expected_exclusions']}，实际 {r['exclusions']}（抽取 {r['extracted']}）"
            )
        if r["recommendation"] != r["expected"]:
            failures.append(f"{r['id']} 建议：预期 {r['expected']}，实际 {r['recommendation']}（{r['score']} 分）")
    return metrics, failures, {"cases": case_results, "materials": mat_results}


# ---------- 门槛与输出 ----------


def flatten(d: dict[str, Any], prefix: str = "") -> dict[str, float]:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, (int, float)):
            out[key] = v
    return out


def check_thresholds(suite: str, metrics: dict[str, Any]) -> list[str]:
    thresholds = json.loads((ROOT / "thresholds.json").read_text(encoding="utf-8"))[suite]
    flat = flatten(metrics)
    problems = [f"{k} = {flat.get(k)}，低于门槛 {v}" for k, v in thresholds.items() if k in flat and flat[k] < v]
    problems += [f"{k} 没有结果（全部失败或没跑到，不是 0 分）" for k in thresholds if k not in flat]
    # 有案例没跑成时，分数只代表跑成的那部分，不能算通过
    for group in ("cases", "materials"):
        part = metrics.get(group) or {}
        if part.get("ok", 0) < part.get("total", 0):
            problems.append(f"{group} 不完整：只跑成 {part['ok']} / {part['total']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="job-hunter-agent evals")
    ap.add_argument("--suite", choices=["program", "llm"], default="program")
    ap.add_argument("--provider", default="claude_cli")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个案例（llm 组）")
    ap.add_argument("--persona", action="append", help="只跑指定求职者，可重复（llm 组）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume", type=Path, help="沿用某次 llm 结果档里已成功的部分，只重跑其余的")
    args = ap.parse_args()

    details: dict[str, Any] = {}
    if args.suite == "program":
        metrics, failures = run_program()
    else:
        metrics, failures, details = run_llm(
            args.provider, args.model, args.limit, args.persona, args.workers, args.resume
        )
    below = check_thresholds(args.suite, metrics)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if failures:
        print("\n个别不符（供检查标注或程式）：")
        for f in failures[:60]:
            print(" -", f)
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = results / f"{args.suite}-{stamp}.json"
    out.write_text(
        json.dumps(
            {"suite": args.suite, "provider": args.provider if args.suite == "llm" else None,
             "model": args.model if args.suite == "llm" else None, "metrics": metrics, "failures": failures,
             "below_threshold": below, **details},
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )  # fmt: skip
    print(f"\n结果：{out}")
    if below:
        print("\n低于门槛：")
        for b in below:
            print(" -", b)
        return 1
    print("\n全部达到门槛。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
