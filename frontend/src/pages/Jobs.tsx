import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, AtsBoard, JobDetail, JobSite, JobSummary, RunJob, SearchRun, SearchRunDetail, SearchSource } from "../api";
import { RECOMMENDATION, RUN_SITE_STATUS, RUN_STATUS, SPONSOR_STATUS, WORK_MODE, salary, show } from "./labels";

interface Prefs {
  target_roles: string[];
  locations: string[];
  search: { total_limit: number };
}

export default function Jobs() {
  const [sites, setSites] = useState<JobSite[]>([]);
  const [source, setSource] = useState<SearchSource | null>(null);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [runs, setRuns] = useState<SearchRun[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [sponsor, setSponsor] = useState(true);
  const [coverage, setCoverage] = useState<{ dataset_count: number } | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const loadSites = useCallback(() => api.get<JobSite[]>("/api/job-sites").then(setSites), []);
  const loadRuns = useCallback(
    () =>
      api.get<SearchRun[]>("/api/search-runs").then((r) => {
        setRuns(r);
        setRunId((cur) => cur ?? r[0]?.id ?? null);
      }),
    [],
  );

  useEffect(() => {
    Promise.all([
      loadSites(),
      loadRuns(),
      api.get<SearchSource>("/api/search/source").then(setSource),
      api.get<{ data: Prefs }>("/api/preferences").then((p) => setPrefs(p.data)),
    ]).catch((e) => setError(e.message));
    api.get<typeof coverage>("/api/sponsor/coverage").then(setCoverage).catch(() => undefined);
  }, [loadSites, loadRuns]);

  const updateSite = async (id: string, patch: Partial<Pick<JobSite, "enabled" | "max_results">>) => {
    setError("");
    try {
      const s = await api.patch<JobSite>(`/api/job-sites/${id}`, patch);
      setSites((all) => all.map((x) => (x.id === id ? s : x)));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const start = async () => {
    setError("");
    setStarting(true);
    try {
      const run = await api.post<SearchRun>("/api/search-runs", { sponsor_history: sponsor });
      setRunId(run.id);
      await loadRuns();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const chosen = sites.filter((s) => s.enabled && s.access_method !== "paste_only");
  const perJob = chosen.reduce((n, s) => n + s.max_results, 0);
  const estimate = Math.min(perJob, prefs?.search.total_limit ?? perJob);
  const busy = runs.some((r) => r.status === "pending" || r.status === "running");

  return (
    <>
      <h2>职位搜索</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>搜索设定</h3>
        {prefs && (
          <p className="muted">
            目标职位：{prefs.target_roles.join("、") || "（未填写）"} · 地点优先顺序：{prefs.locations.join(" → ") || "（未填写）"} ·{" "}
            <Link to="/preferences">修改求职需求</Link>
          </p>
        )}
        {source && (
          <p className={source.ready ? "muted" : "error"}>
            搜索来源：{source.label}
            {!source.ready && (
              <>
                {" "}
                · <Link to="/settings">到设置页处理</Link>（Greenhouse / Lever / Ashby 不需要搜索来源，仍可搜索）
              </>
            )}
          </p>
        )}
        <table>
          <tbody>
            {sites.map((s) => (
              <tr key={s.id}>
                <td style={{ width: 210 }}>
                  <label className="inline">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      disabled={s.access_method === "paste_only"}
                      onChange={(e) => updateSite(s.id, { enabled: e.target.checked })}
                    />
                    <b>{s.name}</b>
                  </label>
                </td>
                <td style={{ width: 120 }}>
                  {s.access_method !== "paste_only" && (
                    <label className="inline">
                      上限
                      <input
                        type="number"
                        min={1}
                        max={100}
                        style={{ width: 60 }}
                        value={s.max_results}
                        onChange={(e) => updateSite(s.id, { max_results: Math.max(1, Math.min(100, Number(e.target.value) || 1)) })}
                      />
                    </label>
                  )}
                </td>
                <td className="muted">
                  {s.access_method === "ats_api"
                    ? `官方公开 API · 已知公司 board ${s.boards} 个`
                    : s.access_method === "paste_only"
                      ? "只支援贴网址 / JD"
                      : "网页搜索 + 读取公开职位页"}
                  {s.limitation_note && ` · ${s.limitation_note}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 12 }}>
          <label className="inline">
            <input type="checkbox" checked={sponsor} onChange={(e) => setSponsor(e.target.checked)} />
            同时查雇主的 H-1B / 绿卡历史
          </label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" onClick={start} disabled={starting || busy || chosen.length === 0}>
            {busy ? "搜索进行中…" : starting ? "正在建立批次…" : "开始搜索"}
          </button>
          <span className="muted">
            已选 {chosen.length} 个网站，最多处理约 {estimate} 个职位（每个职位要读取、抽取并评分，约 20–40 秒）。
          </span>
        </div>
        <p className="muted">
          只读取公开页面；遇到登录、CAPTCHA 或验证页就停下并记录原因，不绕过。本工具不会代你投递或联系雇主。
        </p>
      </div>

      <AtsBoards onChange={loadSites} />

      {coverage && coverage.dataset_count === 0 && (
        <p className="notice">
          尚未导入官方签证资料，签证历史会显示「未查」。导入方式见 README 的「签证资料」一节（<code>scripts/sponsor_data/</code>）。
        </p>
      )}

      {runs.length > 0 && runId && (
        <RunView runId={runId} runs={runs} onSelect={setRunId} onChanged={loadRuns} />
      )}

      <details className="card">
        <summary>
          <b>手动加入职位（贴网址或 JD）</b>
          <span className="muted"> · Handshake 等需要登录的网站请用这里</span>
        </summary>
        <PasteJob />
      </details>

      <AllJobs />
    </>
  );
}

function RunView({
  runId,
  runs,
  onSelect,
  onChanged,
}: {
  runId: string;
  runs: SearchRun[];
  onSelect: (id: string) => void;
  onChanged: () => void;
}) {
  const [run, setRun] = useState<SearchRunDetail | null>(null);
  const [error, setError] = useState("");
  const [showExcluded, setShowExcluded] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [showVisa, setShowVisa] = useState(true);
  const [hideNoRecord, setHideNoRecord] = useState(false);

  const load = useCallback(() => api.get<SearchRunDetail>(`/api/search-runs/${runId}`).then(setRun), [runId]);

  useEffect(() => {
    setRun(null);
    load().catch((e) => setError(e.message));
  }, [load]);

  const active = run?.status === "pending" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => {
      load()
        .then(() => undefined)
        .catch(() => undefined);
    }, 3000);
    return () => clearInterval(t);
  }, [active, load]);

  // 跑完时更新批次清单
  useEffect(() => {
    if (run && !active) onChanged();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  const cancel = async () => {
    try {
      await api.post(`/api/search-runs/${runId}/cancel`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const jobs = (run?.jobs ?? []).filter(
    (j) =>
      (j.outcome === "kept" || (j.outcome === "excluded" && showExcluded) || (j.outcome === "duplicate" && showDuplicates)) &&
      // 只隐藏「范围内查无」；未查、雇主不明一律保留
      !(hideNoRecord && j.sponsor_status === "no_match_in_scope"),
  );
  const p = run?.progress;

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>搜索批次</h3>
        <label className="inline">
          批次
          <select value={runId} onChange={(e) => onSelect(e.target.value)}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id} · {RUN_STATUS[r.status].text}
                {r.counts.kept != null ? ` · 保留 ${r.counts.kept}` : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      {!run && <p className="muted">读取中…</p>}
      {run && (
        <>
          <p className="muted">
            <span className={`badge ${RUN_STATUS[run.status].cls}`}>{RUN_STATUS[run.status].text}</span> 搜索来源：
            {show(run.search_source)} · 开始于 {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
            {run.finished_at && ` · 结束于 ${new Date(run.finished_at).toLocaleString()}`}
            {!run.sponsor_history && " · 本批次未查签证历史"}
          </p>
          {run.error && <p className="error">{run.error}</p>}
          {active && p && (
            <div className="row">
              <span className="notice">
                {p.phase === "searching"
                  ? "正在各网站搜索职位页…"
                  : `正在读取、抽取并评分：${p.done} / ${p.total}`}
              </span>
              <button onClick={cancel}>取消</button>
            </div>
          )}
          <table style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>网站</th>
                <th>状态</th>
                <th>找到</th>
                <th>保留</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {run.sites.map((s) => (
                <tr key={s.site_id}>
                  <td>{s.name}</td>
                  <td>
                    <span className={`badge ${RUN_SITE_STATUS[s.status].cls}`}>{RUN_SITE_STATUS[s.status].text}</span>
                  </td>
                  <td>{s.found_count}</td>
                  <td>{s.status === "searching" ? "—" : s.kept_count}</td>
                  <td className="muted">{linkify(s.message || "")}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {!active && (
            <>
              <div className="row" style={{ marginTop: 16 }}>
                <b>
                  结果：保留 {run.counts.kept ?? 0} · 排除 {run.counts.excluded ?? 0} · 之前批次已有 {run.counts.duplicate ?? 0}
                </b>
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <label className="inline">
                  <input type="checkbox" checked={showExcluded} onChange={(e) => setShowExcluded(e.target.checked)} />
                  显示被排除的职位
                </label>
                <label className="inline">
                  <input type="checkbox" checked={showDuplicates} onChange={(e) => setShowDuplicates(e.target.checked)} />
                  显示之前批次已有的职位
                </label>
                <label className="inline">
                  <input type="checkbox" checked={showVisa} onChange={(e) => setShowVisa(e.target.checked)} />
                  显示签证历史
                </label>
                <label className="inline">
                  <input type="checkbox" checked={hideNoRecord} onChange={(e) => setHideNoRecord(e.target.checked)} />
                  隐藏「范围内查无签证记录」的公司（未查、雇主不明的仍显示）
                </label>
              </div>
              <p className="muted">
                排序：先按你的地点优先顺序，再按发布时间新到旧。分数是契合度估计，不是录取机率。
              </p>
              {jobs.length === 0 ? (
                <p className="muted">没有符合筛选条件的职位。</p>
              ) : (
                <JobTable jobs={jobs} showVisa={showVisa} />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

function linkify(text: string) {
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

function JobTable({ jobs, showVisa }: { jobs: (JobSummary | RunJob)[]; showVisa: boolean }) {
  return (
    <table>
      <tbody>
        {jobs.map((j) => {
          const run = "outcome" in j ? j : null;
          return (
            <tr key={j.id}>
              <td>
                <Link to={`/jobs/${j.id}`}>
                  <b>{j.title}</b>
                </Link>
                <div className="muted">
                  {j.company.display_name} · {show(j.location_text)} · {WORK_MODE[j.work_mode]} ·{" "}
                  {salary(j.salary_min, j.salary_max, j.salary_period)}
                  {j.posted_text ? ` · ${j.posted_text}` : j.posted_at ? ` · 发布于 ${new Date(j.posted_at).toLocaleDateString()}` : " · 发布时间未知"}
                  {run && run.found_on.length > 0 && ` · 来源：${run.found_on.join("、")}`}
                </div>
                {run && run.exclusion_reasons.length > 0 && (
                  <div className="muted" style={{ color: "var(--fail)" }}>
                    排除：{run.exclusion_reasons.map((r) => r.label).join("；")}
                  </div>
                )}
              </td>
              <td style={{ width: 120 }}>
                {j.score != null ? (
                  <>
                    <b>{j.score}</b>{" "}
                    <span className={`badge ${RECOMMENDATION[j.recommendation!].cls}`}>{RECOMMENDATION[j.recommendation!].text}</span>
                  </>
                ) : (
                  <span className="muted">{j.excluded ? "已排除，未评分" : "未评分"}</span>
                )}
              </td>
              <td style={{ width: 230 }}>
                {run?.outcome === "duplicate" && <span className="badge">之前批次已有</span>}{" "}
                <span
                  className={`badge ${j.sponsorship_policy === "explicit_no" ? "fail" : j.sponsorship_policy === "explicit_yes" ? "pass" : "warn"}`}
                >
                  {j.sponsorship_policy === "unclear" ? "sponsor 不明" : j.sponsorship_policy === "explicit_no" ? "不 sponsor" : "sponsor"}
                </span>{" "}
                {showVisa && j.sponsor_status && (
                  <span className={`badge ${SPONSOR_STATUS[j.sponsor_status].cls}`}>签证史：{SPONSOR_STATUS[j.sponsor_status].text}</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
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
    await api.del(`/api/ats-boards/${id}`);
    await load();
    onChange();
  };

  return (
    <details className="card">
      <summary>
        <b>Greenhouse / Lever / Ashby 公司 board（{boards.length}）</b>
        <span className="muted"> · 读过含这些链接的职位页时会自动加入，也可以手动加入</span>
      </summary>
      <div className="row" style={{ marginTop: 10 }}>
        <input
          style={{ flex: 2, minWidth: 260 }}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://job-boards.greenhouse.io/公司名 或 https://jobs.lever.co/公司名"
        />
        <input style={{ flex: 1 }} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="公司名称（选填）" />
        <button onClick={add} disabled={!url.trim()}>
          加入
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <table style={{ marginTop: 8 }}>
        <tbody>
          {boards.map((b) => (
            <tr key={b.company_id}>
              <td>{b.company}</td>
              <td className="muted">
                {b.kind} · {b.token}
              </td>
              <td style={{ width: 80 }}>
                <button onClick={() => remove(b.company_id)}>移除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function AllJobs() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (open && jobs === null) api.get<JobSummary[]>("/api/jobs").then(setJobs).catch(() => setJobs([]));
  }, [open, jobs]);
  return (
    <details className="card" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <b>所有已存的职位</b>
        <span className="muted"> · 包含手动加入与各批次的职位</span>
      </summary>
      {jobs === null ? (
        <p className="muted">读取中…</p>
      ) : jobs.length === 0 ? (
        <p className="muted">还没有职位。</p>
      ) : (
        <JobTable jobs={jobs} showVisa />
      )}
    </details>
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
    <div style={{ marginTop: 10 }}>
      <div className="grid">
        <label>
          职位网址
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        </label>
        <label>
          公司（选填，JD 没写时必填）
          <input value={company} onChange={(e) => setCompany(e.target.value)} />
        </label>
        <label>
          职称（选填）
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
      </div>
      <label style={{ marginTop: 10 }}>
        JD 全文（有贴就优先使用）
        <textarea rows={8} value={jd} onChange={(e) => setJd(e.target.value)} />
      </label>
      <p className="muted">只读取公开网页；遇到登录或验证页会停止，请改贴 JD。</p>
      <button className="primary" onClick={submit} disabled={!!busy || (!url.trim() && !jd.trim())}>
        {busy || "抽取并评分"}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
