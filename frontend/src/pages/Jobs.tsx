import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApplicationStatus, JobPreferences, AtsBoard, JobDetail, JobSite, JobSummary, RunJob, SearchRun, SearchRunDetail, SearchSource } from "../api";
import { StatusSelect } from "./ApplicationControl";
import { APP_STATUS, RUN_SITE_STATUS, RUN_STATUS, SPONSOR_STATUS, WORK_MODE, EMPLOYMENT, PROGRAM, salary, show } from "./labels";
import RoleTags from "./RoleTags";
import { ConfirmButton, Loading, Seg, Spinner, usePopover } from "./ui";


type Bucket = "kept" | "excluded" | "duplicate" | "all" | "applied" | "deleted";
// 已经投出去的状态（「已投递」分组与卡片标签用）
const SUBMITTED: ApplicationStatus[] = ["applied", "interviewing", "offer", "rejected", "ghosted"];
const isSubmitted = (s: ApplicationStatus | null) => !!s && SUBMITTED.includes(s);
type JobRow = JobSummary | RunJob;

const ALL_SAVED = "__all__";
const PART_LABEL = { role: "职位 / 产品内容", tech: "技术栈", experience: "年资与范围", location: "地点与工作方式", recency: "新鲜度与可信度" };
const SEVERITY = { low: "低", medium: "中", high: "高" };
const REC_TAG = { apply: { text: "建议投递", cls: "pass" }, maybe: { text: "可考虑 · 先看风险", cls: "warn" }, skip: { text: "建议跳过", cls: "" } };
const POLICY_TAG = { explicit_yes: { text: "写明提供", cls: "pass" }, explicit_no: { text: "写明不提供", cls: "fail" }, unclear: { text: "JD 没写", cls: "" } };

interface ImportStatus {
  state: "running" | "done" | "failed" | "stale";
  stage?: string;
  stage_label?: string;
  file?: string;
  files_done?: number;
  files_total?: number;
  employers_done?: number;
  employers_total?: number | null;
  message?: string;
  started_at?: string;
}
interface Coverage {
  dataset_count: number;
  import: ImportStatus | null;
}

/** 签证资料导入的状态：导入中显示步骤与进度；失败或中断时说明怎么重跑。完成后不显示。 */
function ImportBanner({ coverage }: { coverage: Coverage }) {
  const s = coverage.import;
  if (!s || s.state === "done") return null;
  if (s.state === "failed" || s.state === "stale") {
    return (
      <p className="error">
        签证资料导入{s.state === "stale" ? "已经很久没有进度，可能中断了" : "失败"}
        {s.message ? `：${s.message}` : "。"}请在 backend/ 重新执行 <code>uv run python ../scripts/sponsor_data/build.py</code>。
      </p>
    );
  }
  // 读档阶段按档案数算，写入阶段按雇主数算
  const pct =
    s.stage === "reading" && s.files_total
      ? Math.round(((s.files_done ?? 0) / s.files_total) * 100)
      : s.stage === "importing" && s.employers_total
        ? Math.round(((s.employers_done ?? 0) / s.employers_total) * 100)
        : null;
  const detail =
    s.stage === "reading" && s.files_total
      ? `第 ${(s.files_done ?? 0) + 1} / ${s.files_total} 个档：${s.file ?? ""}`
      : s.stage === "importing" && s.employers_done
        ? `已写入 ${(s.employers_done ?? 0).toLocaleString()}${s.employers_total ? ` / ${s.employers_total.toLocaleString()}` : ""} 个雇主`
        : "";
  return (
    <div className="notice search-progress" role="status">
      <div className="loading-line">
        <Spinner size={16} />
        <span>
          正在导入官方签证资料 · {s.stage_label || "准备中"}
          {detail && <span className="muted"> · {detail}</span>}
        </span>
      </div>
      <div className="progress-row">
        <div className={`progress${pct == null ? " indeterminate" : ""}`} aria-hidden="true">
          <span style={pct == null ? undefined : { width: `${Math.max(pct, 2)}%` }} />
        </div>
        <b className="progress-pct">{pct == null ? "—" : `${pct}%`}</b>
      </div>
      <div className="muted small">{s.stage === "reading" ? "大的 xlsx 一个要读好几分钟。" : ""}导入完成后，职位的 H-1B / 绿卡会自动更新，不用重新搜索。</div>
    </div>
  );
}

const inBucket = (j: JobRow, b: Bucket) => (b === "all" ? bucketOf(j) !== "deleted" : bucketOf(j) === b);

// 签证历史筛选：依官方资料里查到的 H-1B / PERM 记录（未查的职位只在「全部」出现）
type VisaFilter = "all" | "h1b" | "perm" | "both";
const VISA_FILTER: Record<VisaFilter, { label: string; test: (j: JobRow) => boolean }> = {
  all: { label: "全部签证记录", test: () => true },
  h1b: { label: "查到 H-1B 历史", test: (j) => !!j.sponsor_h1b },
  perm: { label: "查到 PERM", test: (j) => !!j.sponsor_perm },
  both: { label: "两类均查到", test: (j) => !!j.sponsor_h1b && !!j.sponsor_perm },
};

// 每个职位只属于一个分组：已删除 > 已投递 > 搜索结果（待看 / 被排除 / 之前已有）。「全部」= 除已删除以外的所有职位
const bucketOf = (j: JobRow): Exclude<Bucket, "all"> =>
  j.application_status === "dismissed"
    ? "deleted"
    : isSubmitted(j.application_status)
      ? "applied"
      : "outcome" in j
        ? j.outcome
        : j.excluded
          ? "excluded"
          : "kept";

function runLabel(r: SearchRun) {
  const d = new Date(r.started_at ?? r.created_at);
  const time = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `${time} · ${RUN_STATUS[r.status].text}${r.counts.kept != null ? ` · 保留 ${r.counts.kept}` : ""}`;
}

function linkify(text: string): ReactNode[] {
  return text.split(/(https?:\/\/\S+)/g).map((part, i) =>
    /^https?:\/\//.test(part) ? (
      <a key={i} href={part} target="_blank" rel="noreferrer noopener" style={{ wordBreak: "break-all" }}>
        {part}
      </a>
    ) : (
      part
    ),
  );
}

export default function Jobs() {
  const [sites, setSites] = useState<JobSite[]>([]);
  const [source, setSource] = useState<SearchSource | null>(null);
  const [prefs, setPrefs] = useState<JobPreferences | null>(null);
  const [runs, setRuns] = useState<SearchRun[] | null>(null);
  const [view, setView] = useState<string | null>(null); // 批次 id 或 ALL_SAVED
  const [run, setRun] = useState<SearchRunDetail | null>(null);
  const [saved, setSaved] = useState<JobSummary[] | null>(null);
  const [removed, setRemoved] = useState<Set<string>>(new Set()); // 永久删除的
  const [statusOf, setStatusOf] = useState<Record<string, ApplicationStatus | null>>({}); // 这页里改过的投递状态
  const [sponsor, setSponsor] = useState(true);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [bucket, setBucket] = useState<Bucket>("kept");
  const [visaFilter, setVisaFilter] = useState<VisaFilter>("all");
  const [sort, setSort] = useState<"place" | "score">("place");
  // 已投递 / 已删除：「地点优先」换成按时间、新的在上
  const timeSorted = (bucket === "applied" || bucket === "deleted") && sort === "place";
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [starting, setStarting] = useState(false);
  const pop = usePopover<"roles" | "sources" | "paste">();
  const [savingRoles, setSavingRoles] = useState(false);

  const loadSites = useCallback(() => api.get<JobSite[]>("/api/job-sites").then(setSites), []);
  const loadRuns = useCallback(
    () =>
      api.get<SearchRun[]>("/api/search-runs").then((r) => {
        setRuns(r);
        setView((cur) => cur ?? r[0]?.id ?? ALL_SAVED);
      }),
    [],
  );

  useEffect(() => {
    Promise.all([
      loadSites(),
      loadRuns(),
      api.get<SearchSource>("/api/search/source").then(setSource),
      api.get<{ data: JobPreferences }>("/api/preferences").then((p) => setPrefs(p.data)),
    ]).catch((e) => setError(e.message));
    api.get<Coverage>("/api/sponsor/coverage").then(setCoverage).catch(() => undefined);
  }, [loadSites, loadRuns]);

  // 签证资料导入中：每 5 秒更新进度；导入完成时重新读取职位，签证历史就会补上
  const importing = coverage?.import?.state === "running";
  useEffect(() => {
    if (!importing) return;
    const t = setInterval(() => {
      api
        .get<Coverage>("/api/sponsor/coverage")
        .then((c) => {
          setCoverage(c);
          if (c.import?.state === "done") {
            setNotice(`签证资料导入完成：${c.import.message ?? ""}职位的 H-1B / 绿卡已更新。`);
            (view === ALL_SAVED ? loadSaved() : loadRun()).catch(() => undefined);
          }
        })
        .catch(() => undefined);
    }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [importing]);

  const runId = view && view !== ALL_SAVED ? view : null;
  const loadRun = useCallback(() => (runId ? api.get<SearchRunDetail>(`/api/search-runs/${runId}`).then(setRun) : Promise.resolve()), [runId]);

  useEffect(() => {
    setRun(null);
    loadRun().catch((e) => setError(e.message));
  }, [loadRun]);

  const loadSaved = useCallback(() => api.get<JobSummary[]>("/api/jobs").then(setSaved), []);
  useEffect(() => {
    if (view === ALL_SAVED) loadSaved().catch((e) => setError(e.message));
  }, [view, loadSaved]);

  // 拉黑后：重新读取，相符的职位会出现在「已删除」
  const reloadJobs = (message: string) => {
    setNotice(message);
    setStatusOf({});
    (view === ALL_SAVED ? loadSaved() : loadRun()).catch((e) => setError(e.message));
  };

  const active = run?.status === "pending" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => void loadRun().catch(() => undefined), 3000);
    return () => clearInterval(t);
  }, [active, loadRun]);

  // 跑完时更新批次清单
  useEffect(() => {
    if (run && !active) void loadRuns().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  const updateSite = async (id: string, patch: Partial<Pick<JobSite, "enabled" | "max_results">>) => {
    setError("");
    try {
      const s = await api.patch<JobSite>(`/api/job-sites/${id}`, patch);
      setSites((all) => all.map((x) => (x.id === id ? s : x)));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // 目标职位 tag 开关：直接保存到求职需求
  const saveRoles = async (target_roles: string[], paused_roles: string[]) => {
    if (!prefs) return;
    const before = prefs;
    setPrefs({ ...prefs, target_roles, paused_roles }); // 先更新画面
    setSavingRoles(true);
    setError("");
    try {
      const r = await api.put<{ data: JobPreferences }>("/api/preferences", { ...before, target_roles, paused_roles });
      setPrefs(r.data);
    } catch (e) {
      setPrefs(before);
      setError((e as Error).message);
    } finally {
      setSavingRoles(false);
    }
  };

  const start = async () => {
    setError("");
    setStarting(true);
    try {
      const r = await api.post<SearchRun>("/api/search-runs", { sponsor_history: sponsor });
      setView(r.id);
      setBucket("kept");
      await loadRuns();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!runId) return;
    try {
      await api.post(`/api/search-runs/${runId}/cancel`);
      await loadRun();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const chosen = sites.filter((s) => s.enabled && s.access_method !== "paste_only");
  const perJob = chosen.reduce((n, s) => n + s.max_results, 0);
  const estimate = Math.min(perJob, prefs?.search.total_limit ?? perJob);
  const busy = (runs ?? []).some((r) => r.status === "pending" || r.status === "running");
  const boardCount = sites.reduce((n, s) => n + (s.access_method === "ats_api" ? s.boards : 0), 0);

  const all = useMemo<JobRow[]>(() => {
    const list: JobRow[] = view === ALL_SAVED ? (saved ?? []) : (run?.jobs ?? []);
    return list.filter((j) => !removed.has(j.id)).map((j) => (j.id in statusOf ? { ...j, application_status: statusOf[j.id] } : j));
  }, [view, saved, run, removed, statusOf]);

  const visible = useMemo(() => {
    const list = all.filter(
      (j) =>
        inBucket(j, bucket) &&
        VISA_FILTER[visaFilter].test(j),
    );
    if (sort === "score") return [...list].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    if (timeSorted) {
      // 已投递按投递时间、已删除按删除时间，新的在上面
      const t = (j: JobRow) => Date.parse((bucket === "applied" ? j.applied_at : j.status_at) ?? j.status_at ?? "") || 0;
      return [...list].sort((a, b) => t(b) - t(a));
    }
    return list;
  }, [all, bucket, visaFilter, sort, timeSorted]);

  const count = (b: Bucket) => all.filter((j) => inBucket(j, b)).length;
  const paused = new Set(prefs?.paused_roles ?? []);
  const roles = (prefs?.target_roles ?? []).filter((r) => !paused.has(r)); // 启用中的职位
  const p = run?.progress;
  const pct = p && p.total ? Math.round((p.done / p.total) * 100) : 0;
  const searching = active && (p?.phase === "searching" || !p?.total);
  const bad = run ? run.sites.filter((s) => s.status === "blocked" || s.status === "failed").length : 0;
  const sourceSummary = active
    ? p?.phase === "searching"
      ? "正在各网站搜索…"
      : `${run!.sites.length - bad} 个正常 · ${bad} 个有问题`
    : `${chosen.length} 个来源 · 最多 ${estimate} 个`;

  return (
    <div className="stack">
      {error && <p className="error">{error}</p>}
      {notice && (
        <p className="notice row between">
          <span>{notice}</span>
          <button type="button" className="link" onClick={() => setNotice("")}>
            知道了
          </button>
        </p>
      )}
      {source && !source.ready && (
        <p className="error">
          搜索来源：{source.label} · <Link to="/settings">到模型连接处理</Link>（Greenhouse / Lever / Ashby 不需要搜索来源，仍可搜索）
        </p>
      )}
      {coverage && <ImportBanner coverage={coverage} />}
      {coverage && coverage.dataset_count === 0 && !coverage.import && (
        <p className="notice">
          尚未导入官方签证资料，签证历史会显示「未查」。导入方式见 README 的「签证资料」一节（<code>scripts/sponsor_data/</code>）。
        </p>
      )}

      <section className="search-row" aria-label="搜索条件" ref={pop.ref}>
        <div className="search-cells">
          <div className="pop-wrap">
            <button type="button" className="cell" aria-expanded={pop.open === "roles"} onClick={() => pop.toggle("roles")}>
              <span className="cell-label">目标职位 ▾</span>
              <span className="cell-value one-line">
                {roles.length ? roles[0] : "未启用任何职位"}
                {roles.length > 1 && <span className="muted"> +{roles.length - 1}</span>}
                {paused.size > 0 && <span className="muted small"> · {paused.size} 个停用</span>}
              </span>
            </button>
            {pop.open === "roles" && prefs && (
              <div className="pop">
                <div className="row between">
                  <b>目标职位</b>
                  <span className="muted small">{savingRoles ? <><Spinner /> 保存中</> : "改动会直接保存"}</span>
                </div>
                <RoleTags roles={prefs.target_roles} paused={prefs.paused_roles} onChange={saveRoles} />
                <div className="muted small">点 tag 切换启用 / 停用；停用的不会拿去搜索和评分。其他条件到 <Link to="/preferences">求职需求</Link> 修改。</div>
              </div>
            )}
          </div>
          <Link to="/preferences" className="cell">
            <span className="cell-label">地点顺序</span>
            <span className="cell-value">{prefs?.locations.filter(Boolean).join(" → ") || "未填写"}</span>
          </Link>
          <div className="pop-wrap">
            <button type="button" className="cell" aria-expanded={pop.open === "sources"} onClick={() => pop.toggle("sources")}>
              <span className="cell-label">来源 ▾</span>
              <span className="cell-value">{sourceSummary}</span>
            </button>
            {pop.open === "sources" && <SourcesPanel sites={sites} run={active ? run : null} boardCount={boardCount} onUpdate={updateSite} onBoardsChanged={loadSites} />}
          </div>
          <label className="cell">
            <input type="checkbox" checked={sponsor} onChange={(e) => setSponsor(e.target.checked)} />
            <span>
              <span className="cell-label">签证历史</span>
              <span className="cell-value">同时查 H-1B / 绿卡</span>
            </span>
          </label>
        </div>

        {active ? (
          <button type="button" onClick={cancel}>
            {p?.phase === "searching" ? "搜索中" : `${p?.done ?? 0} / ${p?.total ?? 0}`} · 取消
          </button>
        ) : (
          <button type="button" className="primary" onClick={start} disabled={starting || busy || chosen.length === 0}>
            {busy ? <><Spinner />搜索进行中…</> : starting ? <><Spinner />正在建立批次…</> : "开始搜索"}
          </button>
        )}

        <div className="pop-wrap">
          <button type="button" aria-expanded={pop.open === "paste"} onClick={() => pop.toggle("paste")}>
            贴职位
          </button>
          {pop.open === "paste" && (
            <div className="pop right">
              <PasteJob />
            </div>
          )}
        </div>
      </section>

      <section className="filter-row" aria-label="结果筛选">
        <div className="row">
          <select aria-label="搜索批次" value={view ?? ""} onChange={(e) => setView(e.target.value)} style={{ maxWidth: "100%" }}>
            {(runs ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {runLabel(r)}
              </option>
            ))}
            <option value={ALL_SAVED}>所有已存的职位</option>
          </select>
          <Seg<Bucket>
            label="职位分组"
            value={bucket}
            onChange={setBucket}
            options={[
              { value: "kept", label: `待看 ${count("kept")}` },
              { value: "applied", label: `已投递 ${count("applied")}` },
              { value: "excluded", label: `被排除 ${count("excluded")}` },
              { value: "duplicate", label: `之前已有 ${count("duplicate")}` },
              { value: "all", label: `全部 ${count("all")}` },
              { value: "deleted", label: `已删除 ${count("deleted")}` },
            ]}
          />
        </div>
        <div className="row">
          <select aria-label="签证筛选" value={visaFilter} onChange={(e) => setVisaFilter(e.target.value as VisaFilter)}>
            {(Object.keys(VISA_FILTER) as VisaFilter[]).map((k) => (
              <option key={k} value={k}>
                {VISA_FILTER[k].label}
              </option>
            ))}
          </select>
          <select aria-label="排序" value={sort} onChange={(e) => setSort(e.target.value as "place" | "score")}>
            <option value="place">{bucket === "applied" ? "排序：最近投递" : bucket === "deleted" ? "排序：最近删除" : "排序：地点优先"}</option>
            <option value="score">排序：匹配分数</option>
          </select>
        </div>
      </section>

      {run?.error && <p className="error">{run.error}</p>}

      <section className="stack" aria-label="职位列表">
        {visible.map((j) => (
          <JobCard
            key={j.id}
            job={j}
            onStatus={(st) => setStatusOf((m) => ({ ...m, [j.id]: st }))}
            onRemoved={() => setRemoved((s) => new Set(s).add(j.id))}
            onBlacklisted={reloadJobs}
          />
        ))}
        {(runs === null || (view === ALL_SAVED && saved === null) || (runId && run === null)) && !error && <Loading className="card" text="读取职位中…" />}
        {runs && !(view === ALL_SAVED && saved === null) && !(runId && run === null) && visible.length === 0 && !active && (
          <div className="card muted">{bucket === "deleted" ? "没有已删除的职位。" : bucket === "applied" ? "还没有标记为已投递的职位。投完后按职位卡上的「我已投递」。" : "没有符合筛选条件的职位。"}</div>
        )}
        {active && (
          <div className="card search-progress">
            <div className="loading-line muted">
              <Spinner size={18} />
              <span>
                {searching ? "正在各网站搜索职位…" : "正在读取、评分职位…"}
                {visible.length === 0 ? "处理好的职位会显示在这里。" : "处理好的职位会陆续加进来。"}可以离开这个页面，搜索会继续。
              </span>
            </div>
            <div className="progress-row">
              <div
                className={`progress${searching ? " indeterminate" : ""}`}
                role="progressbar"
                aria-label="搜索进度"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={searching ? undefined : pct}
              >
                <span style={searching ? undefined : { width: `${Math.max(pct, 2)}%` }} />
              </div>
              <b className="progress-pct">{searching ? "—" : `${pct}%`}</b>
            </div>
            <div className="muted small">{searching ? "还在找职位网址，找完才知道总数" : `已处理 ${p?.done ?? 0} / ${p?.total ?? 0} 个职位`}</div>
          </div>
        )}
      </section>
    </div>
  );
}

function SourcesPanel({
  sites,
  run,
  boardCount,
  onUpdate,
  onBoardsChanged,
}: {
  sites: JobSite[];
  run: SearchRunDetail | null;
  boardCount: number;
  onUpdate: (id: string, patch: Partial<Pick<JobSite, "enabled" | "max_results">>) => void;
  onBoardsChanged: () => void;
}) {
  const [boards, setBoards] = useState(false);
  if (boards) {
    return (
      <div className="pop">
        <AtsBoards onChange={onBoardsChanged} />
        <div>
          <button type="button" className="link" onClick={() => setBoards(false)}>
            ← 返回来源
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="pop">
      <div>
        {sites.map((s) => {
          const live = run?.sites.find((x) => x.site_id === s.id);
          const pasteOnly = s.access_method === "paste_only";
          return (
            <div className="site-row" key={s.id}>
              <label className="inline">
                <input type="checkbox" checked={s.enabled} disabled={pasteOnly} onChange={(e) => onUpdate(s.id, { enabled: e.target.checked })} />
                <span>
                  <b>{s.name}</b>
                  <span className="muted small" style={{ display: "block" }}>
                    {live ? (
                      <>
                        {RUN_SITE_STATUS[live.status].text} · 找到 {live.found_count}
                        {live.message && <> · {linkify(live.message)}</>}
                      </>
                    ) : pasteOnly ? (
                      "只支援贴网址 / JD"
                    ) : s.access_method === "ats_api" ? (
                      `官方 API · ${s.boards} 个公司 board`
                    ) : (
                      `网页搜索 · 只读公开职位页${s.limitation_note ? ` · ${s.limitation_note}` : ""}`
                    )}
                  </span>
                </span>
              </label>
              {!pasteOnly && (
                <label className="inline">
                  上限
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={s.max_results}
                    onChange={(e) => onUpdate(s.id, { max_results: Math.max(1, Math.min(100, Number(e.target.value) || 1)) })}
                  />
                </label>
              )}
            </div>
          );
        })}
      </div>
      <div className="row between">
        <span className="muted">每个职位约 20–40 秒</span>
        <button type="button" className="link" onClick={() => setBoards(true)}>
          管理公司 board（{boardCount}）
        </button>
      </div>
      <div className="muted small">只读取公开页面；遇到登录、CAPTCHA 或验证页就停下并记录原因，不绕过。本工具不会代你投递或联系雇主。</div>
    </div>
  );
}

function JobCard({
  job,
  onStatus,
  onRemoved,
  onBlacklisted,
}: {
  job: JobRow;
  onStatus: (s: ApplicationStatus | null) => void;
  onRemoved: () => void;
  onBlacklisted: (message: string) => void;
}) {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [status, setStatus] = useState<ApplicationStatus | null>(job.application_status);
  const [appliedAt, setAppliedAt] = useState<string | null>(job.applied_at);
  useEffect(() => setAppliedAt(job.applied_at), [job.applied_at]);
  const [error, setError] = useState("");
  const run = "outcome" in job ? job : null;

  useEffect(() => setStatus(job.application_status), [job.application_status]);
  const changed = (s: ApplicationStatus | null) => {
    setStatus(s);
    onStatus(s);
  };

  const toggle = () => {
    setOpen(!open);
    if (!open && !detail) api.get<JobDetail>(`/api/jobs/${job.id}`).then(setDetail).catch((e) => setError(e.message));
  };

  const markApplied = async () => {
    setError("");
    try {
      const a = await api.put<{ applied_at: string | null }>(`/api/jobs/${job.id}/application`, { status: "applied" });
      setAppliedAt(a.applied_at);
      changed("applied");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // 删除 = 投递状态改成 dismissed（可还原，统计里看得到）；已删除的才能永久删除
  const dismiss = async () => {
    setError("");
    try {
      await api.put(`/api/jobs/${job.id}/application`, { status: "dismissed" });
      changed("dismissed");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const restore = async () => {
    setError("");
    try {
      const a = await api.post<{ status: ApplicationStatus }>(`/api/jobs/${job.id}/application/restore`);
      changed(a.status);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const purge = async () => {
    try {
      await api.del(`/api/jobs/${job.id}`);
      onRemoved();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const deleted = status === "dismissed";

  const excluded = run ? run.outcome === "excluded" : job.excluded;
  const rec = job.recommendation ? REC_TAG[job.recommendation] : excluded ? { text: "已排除", cls: "fail" } : { text: "未评分", cls: "" };
  const policy = POLICY_TAG[job.sponsorship_policy];
  const visa = job.sponsor_status ? SPONSOR_STATUS[job.sponsor_status] : null;
  const posted = job.posted_text || (job.posted_at ? `发布于 ${new Date(job.posted_at).toLocaleDateString()}` : "发布时间未知");
  const note =
    run && run.exclusion_reasons.length > 0
      ? `排除原因：${run.exclusion_reasons.map((r) => r.label).join("；")}`
      : run?.outcome === "duplicate"
        ? "在之前的搜索批次里已经出现过。"
        : EMPLOYMENT[job.employment_type];
  const verified = job.status === "unverified" ? "未在官网核实是否仍在招聘" : job.status === "expired" ? "已下架 / 过期" : "仍在招聘（已读取页面）";
  const sourceLine = [run?.found_on.join("、"), job.company.display_name].filter(Boolean).join(" · ");
  const m = detail?.match;

  return (
    <article className={`job-card${isSubmitted(status) ? " submitted" : ""}`}>
      <div className="job-main">
        <div className="job-info">
          <div className="muted">{sourceLine}</div>
          <h2 className="job-title">
            <Link to={`/jobs/${job.id}`}>{job.title}</Link>
          </h2>
          <div className="job-tags">
            {isSubmitted(status) && (
              <span className={`badge applied-tag ${status === "rejected" ? "fail" : status === "ghosted" ? "warn" : ""}`}>
                ✓ {APP_STATUS[status!].text}
                {appliedAt && ` · ${new Date(appliedAt).toLocaleDateString(undefined, { month: "numeric", day: "numeric" })}${status === "applied" ? "" : " 投递"}`}
              </span>
            )}
            <span className={`badge ${rec.cls}`}>{rec.text}</span>
            <span className={`badge ${policy.cls}`}>Sponsorship：{policy.text}</span>
            {visa && <span className={`badge ${visa.cls}`}>H-1B / 绿卡：{visa.text}</span>}
          </div>
          <div>
            {show(job.location_text)} · {WORK_MODE[job.work_mode]}
          </div>
          <div>
            <b style={{ fontWeight: 600 }}>{salary(job.salary_min, job.salary_max, job.salary_period)}</b> · {posted}
          </div>
          <div className="muted" style={{ marginTop: 2, color: excluded ? "var(--fail)" : undefined }}>
            {note}
          </div>
        </div>
        <div className="job-score">
          <b>
            {job.score ?? "未评分"}
            {job.score != null && <span className="muted small"> / 100</span>}
          </b>
          <span className="muted small">{job.score != null ? "匹配度估计" : excluded ? "已排除" : "尚未评分"}</span>
        </div>
      </div>

      <button type="button" className="job-toggle" aria-expanded={open} onClick={toggle}>
        {open ? "▼" : "▶"} 匹配理由、风险和签证历史
      </button>
      {open && !detail && !error && <Loading className="pad-x" />}
      {open && detail && (
        <div className="job-more">
          <div>
            <h3>为什么匹配</h3>
            {!m && <p className="muted">{excluded ? "这个职位已被排除，没有评分。" : "尚未评分。"}</p>}
            {m && m.reasons.length === 0 && <p className="muted">没有可以引用履历证据的理由。</p>}
            {m?.reasons.map((r, i) => (
              <div className="reason" key={i}>
                <div>{r.text}</div>
                {r.chunk_ids.map((c) => (
                  <div className="evidence-box" key={c}>
                    履历证据：{detail.evidence[c] ?? c}
                  </div>
                ))}
              </div>
            ))}
            <h3>缺口与风险</h3>
            {(!m || m.gaps.length === 0) && <p className="muted">无。</p>}
            {m?.gaps.map((g, i) => (
              <div className="reason" key={i}>
                <b style={{ color: g.severity === "high" ? "var(--fail)" : "var(--warn)", fontSize: 12 }}>{SEVERITY[g.severity]}</b> {g.text}
              </div>
            ))}
          </div>
          <div>
            {m && (
              <>
                <h3>分项</h3>
                {(Object.keys(PART_LABEL) as (keyof typeof PART_LABEL)[]).map((k) => (
                  <div className="part" key={k} title={m.breakdown[k].reason}>
                    <div className="part-head">
                      <span>{PART_LABEL[k]}</span>
                      <span className="muted">
                        {m.breakdown[k].score} / {m.breakdown[k].max}
                      </span>
                    </div>
                    <div className="part-track">
                      <span className="part-fill" style={{ width: `${(m.breakdown[k].score / Math.max(m.breakdown[k].max, 1)) * 100}%` }} />
                    </div>
                  </div>
                ))}
                <p className="muted small">分数是契合度估计，不是录取概率。</p>
              </>
            )}
            <h3>公司签证历史</h3>
            {detail.sponsor ? (
              <>
                <div>
                  {SPONSOR_STATUS[detail.sponsor.status].text} · <span className="muted">{SPONSOR_STATUS[detail.sponsor.status].desc}</span>
                </div>
                {Object.entries(detail.sponsor.summary.programs).map(([prog, years]) => (
                  <div className="muted" key={prog}>
                    {PROGRAM[prog] ?? prog}：{years.map((y) => `FY${y.fiscal_year}`).join("、")}
                  </div>
                ))}
              </>
            ) : (
              <div className="muted">未查。</div>
            )}
            <Link to={`/jobs/${job.id}`} className="btn" style={{ border: 0, padding: 0, color: "var(--accent-text)" }}>
              查看 JD 全文与完整记录
            </Link>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      <div className="job-foot">
        <div className="muted">{verified}</div>
        <div className="job-actions">
          {job.apply_url && (
            <a className="btn accent" href={job.apply_url} target="_blank" rel="noopener noreferrer">
              打开职位 / 自行申请 ↗
            </a>
          )}
          <button type="button" onClick={() => nav(`/materials?job=${job.id}&kind=cover_letter`)}>
            生成 Cover Letter
          </button>
          <button type="button" onClick={() => nav(`/materials?job=${job.id}&kind=qa`)}>
            申请问答
          </button>
          {!deleted && (status === null || status === "saved") && (
            <button type="button" onClick={markApplied}>
              我已投递
            </button>
          )}
          {deleted ? (
            <>
              <button type="button" onClick={restore}>
                还原
              </button>
              <ConfirmButton className="danger" message={`永久删除「${job.title}」？评分、来源、投递记录都会一起删除，无法复原。`} confirmLabel="确定永久删除" onConfirm={purge}>
                永久删除
              </ConfirmButton>
            </>
          ) : (
            <>
              <StatusSelect jobId={job.id} status={status} onChange={changed} />
              <BlockButton job={job} onDone={onBlacklisted} />
              <ConfirmButton className="danger" message={`删除「${job.title}」？会移到「已删除」，可以还原。`} onConfirm={dismiss}>
                删除
              </ConfirmButton>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

/** 拉黑：选「这家公司」或「类似职位」（职称关键词可改短，例如只留 Sales Engineer）。
 * 加进求职需求的黑名单；已存的相符职位移到「已删除」，之后搜索直接排除。 */
function BlockButton({ job, onDone }: { job: JobRow; onDone: (message: string) => void }) {
  const pop = usePopover<"block">();
  const [kind, setKind] = useState<"company" | "title">("company");
  const [phrase, setPhrase] = useState(job.title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post<{ dismissed: number; kept_submitted: number }>("/api/blacklist", {
        kind,
        value: kind === "company" ? job.company.display_name : phrase.trim(),
      });
      pop.setOpen(null);
      const what = kind === "company" ? `公司「${job.company.display_name}」` : `职位「${phrase.trim()}」`;
      onDone(
        `已把${what}加进黑名单，${r.dismissed} 个相符的职位移到「已删除」` +
          (r.kept_submitted ? `；${r.kept_submitted} 个已投递的保留` : "") +
          "。之后的搜索会排除它们。",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pop-wrap" ref={pop.ref}>
      <button type="button" aria-expanded={pop.open === "block"} onClick={() => pop.toggle("block")}>
        拉黑 ▾
      </button>
      {pop.open === "block" && (
        <div className="pop right up">
          <b>拉黑后不再看到</b>
          <label className="inline">
            <input type="radio" name={`block-${job.id}`} checked={kind === "company"} onChange={() => setKind("company")} />
            <span>
              这家公司：<b>{job.company.display_name}</b>
              <span className="muted small" style={{ display: "block" }}>这家公司的所有职位</span>
            </span>
          </label>
          <label className="inline">
            <input type="radio" name={`block-${job.id}`} checked={kind === "title"} onChange={() => setKind("title")} />
            <span style={{ flex: 1 }}>
              类似职位
              <span className="muted small" style={{ display: "block" }}>职称里含这组词的职位（任何公司）；可以删短，例如只留「Sales Engineer」</span>
            </span>
          </label>
          {kind === "title" && <input aria-label="要拉黑的职称关键词" value={phrase} onChange={(e) => setPhrase(e.target.value)} />}
          <div className="muted small">已存的相符职位会移到「已删除」（可还原，已投递的保留），之后搜索也会排除。黑名单可在「求职需求 → 黑名单」修改。</div>
          {error && <p className="error">{error}</p>}
          <div className="row">
            <button type="button" className="danger-solid" onClick={submit} disabled={busy || (kind === "title" && !phrase.trim())}>
              {busy ? (
                <>
                  <Spinner />
                  拉黑中…
                </>
              ) : (
                "确定拉黑"
              )}
            </button>
            <button type="button" onClick={() => pop.setOpen(null)}>
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AtsBoards({ onChange }: { onChange: () => void }) {
  const [boards, setBoards] = useState<AtsBoard[]>([]);
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => api.get<AtsBoard[]>("/api/ats-boards").then(setBoards), []);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  const add = async () => {
    setError("");
    try {
      await api.post("/api/ats-boards", { url, company });
      setUrl("");
      setCompany("");
      await load();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const remove = async (id: string) => {
    setError("");
    try {
      await api.del(`/api/ats-boards/${id}`);
      await load();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <div className="muted small">读过含这些链接的职位页时会自动加入，也可以手动加入。</div>
      <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Greenhouse / Lever / Ashby 的公司 board 网址" aria-label="公司 board 网址" />
      <div className="row">
        <input style={{ flex: 1, minWidth: 0 }} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="公司名称（选填）" aria-label="公司名称" />
        <button type="button" onClick={add} disabled={!url.trim()}>
          加入
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div style={{ maxHeight: 260, overflow: "auto" }}>
        {boards.map((b) => (
          <div className="site-row" key={b.company_id}>
            <span>
              {b.company}
              <span className="muted small" style={{ display: "block" }}>
                {b.kind} · {b.token}
              </span>
            </span>
            <button type="button" className="link danger" onClick={() => remove(b.company_id)}>
              移除
            </button>
          </div>
        ))}
      </div>
    </>
  );
}

function PasteJob() {
  const nav = useNavigate();
  const [url, setUrl] = useState("");
  const [jd, setJd] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    try {
      setBusy(jd.trim() ? "正在抽取职位资料…" : "正在读取网页并抽取职位资料…");
      const r = await api.post<{ job: JobDetail; notes: string[] }>("/api/jobs/ingest", {
        url: url || null,
        jd_text: jd || null,
        company,
        title,
      });
      setBusy("正在计算匹配评分…");
      await api.post(`/api/jobs/${r.job.id}/match`).catch(() => undefined); // 失败时详情页会显示原因与重试按钮
      nav(`/jobs/${r.job.id}`, { state: { notes: r.notes } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <label>
        职位网址
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
      </label>
      <label>
        或贴 JD 全文（有贴就优先使用）
        <textarea rows={6} value={jd} onChange={(e) => setJd(e.target.value)} />
      </label>
      <div className="row">
        <input style={{ flex: 1, minWidth: 0 }} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="公司（JD 没写时必填）" aria-label="公司" />
        <input style={{ flex: 1, minWidth: 0 }} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="职称（选填）" aria-label="职称" />
      </div>
      <div className="muted small">Handshake 等需要登录的网站请用这里。只读取公开网页；遇到登录或验证页会停止，请改贴 JD。</div>
      <button type="button" className="primary" onClick={submit} disabled={!!busy || (!url.trim() && !jd.trim())}>
        {busy ? <><Spinner />{busy}</> : "抽取并评分"}
      </button>
      {error && <p className="error">{error}</p>}
    </>
  );
}
