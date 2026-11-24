import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Paper } from "@/components/ui/paper";
import { Progress } from "@/components/ui/progress";
import { Stamp } from "@/components/ui/stamp";
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApplicationStatus, BrowserStatus, DEMO, JobPreferences, AtsBoard, JobDetail, JobSite, JobSummary, RunJob, SearchRun, SearchRunDetail, SearchSource } from "../api";
import { StatusSelect } from "./ApplicationControl";
import { JobMaterials, MaterialKind } from "./MaterialsPanel";
import OutreachPanel from "./OutreachPanel";
import { APP_STATUS, RUN_SITE_STATUS, RUN_STATUS, SPONSOR_STATUS, WORK_MODE, EMPLOYMENT, PROGRAM, salary, show } from "./labels";
import RoleTags from "./RoleTags";
import { ConfirmButton, Loading, Modal, Seg, Spinner, usePopover } from "./ui";
import { locale, t } from "../i18n";


type Bucket = "kept" | "excluded" | "duplicate" | "all" | "applied" | "deleted";
// 已经投出去的状态（「已投递」分组与卡片标签用）
const SUBMITTED: ApplicationStatus[] = ["referred", "applied", "interviewing", "offer", "rejected", "ghosted"];
const isSubmitted = (s: ApplicationStatus | null) => !!s && SUBMITTED.includes(s);
type JobRow = JobSummary | RunJob;

const ALL_SAVED = "__all__";
const SHORT_NOTICE_KEY = "jobs.shortNoticeHidden";
const PROGRAM_SHORT = { lca: "H-1B LCA", uscis_h1b: t("H-1B 批准"), perm: t("绿卡 PERM") };
const PART_LABEL = { role: t("职位 / 产品内容"), tech: t("技术栈"), experience: t("年资与范围"), location: t("地点与工作方式"), recency: t("新鲜度与可信度") };
const SEVERITY = { low: t("低"), medium: t("中"), high: t("高") };
const REC_TAG = { apply: { text: t("建议投递"), cls: "pass" }, maybe: { text: t("可考虑 · 先看风险"), cls: "warn" }, skip: { text: t("建议跳过"), cls: "" } };
const POLICY_TAG = { explicit_yes: { text: t("写明提供"), cls: "pass" }, explicit_no: { text: t("写明不提供"), cls: "fail" }, unclear: { text: t("JD 没写"), cls: "" } };

// 导入步骤（后端 import_status.STAGES 的代码）
const STAGE_LABEL: Record<string, string> = {
  reading: "读取官方原始档",
  summarizing: "写出汇总档",
  importing: "写入数据库",
  recomputing: "重算职位公司的签证状态",
};

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
        {s.state === "stale" ? t("签证资料导入已经很久没有进度，可能中断了") : t("签证资料导入失败")}
        {s.message ? `: ${s.message}` : "."} {t("请在 backend/ 重新执行")} <code>uv run python ../scripts/sponsor_data/build.py</code>
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
      ? t("第 {i} / {n} 个档：{file}", { i: (s.files_done ?? 0) + 1, n: s.files_total, file: s.file ?? "" })
      : s.stage === "importing" && s.employers_done
        ? t("已写入 {done}{total} 个雇主", { done: (s.employers_done ?? 0).toLocaleString(locale), total: s.employers_total ? ` / ${s.employers_total.toLocaleString(locale)}` : "" })
        : "";
  return (
    <div className="notice search-progress" role="status">
      <div className="loading-line">
        <Spinner size={16} />
        <span>
          {t("正在导入官方签证资料")} · {s.stage ? t(STAGE_LABEL[s.stage] ?? s.stage) : t("准备中")}
          {detail && <span className="muted"> · {detail}</span>}
        </span>
      </div>
      <div className="progress-row">
        <div className={`progress${pct == null ? " indeterminate" : ""}`} aria-hidden="true">
          <span style={pct == null ? undefined : { width: `${Math.max(pct, 2)}%` }} />
        </div>
        <b className="progress-pct">{pct == null ? "—" : `${pct}%`}</b>
      </div>
      <div className="muted small">{s.stage === "reading" ? t("大的 xlsx 一个要读好几分钟。") : ""}{t("导入完成后，职位的 H-1B / 绿卡会自动更新，不用重新搜索。")}</div>
    </div>
  );
}

const inBucket = (j: JobRow, b: Bucket) => (b === "all" ? bucketOf(j) !== "deleted" : bucketOf(j) === b);

// 签证历史筛选：依官方资料里查到的 H-1B / PERM 记录（未查的职位只在「全部」出现）
type VisaFilter = "all" | "h1b" | "perm" | "both";
const VISA_FILTER: Record<VisaFilter, { label: string; test: (j: JobRow) => boolean }> = {
  all: { label: t("全部签证记录"), test: () => true },
  h1b: { label: t("查到 H-1B 历史"), test: (j) => !!j.sponsor_h1b },
  perm: { label: t("查到 PERM"), test: (j) => !!j.sponsor_perm },
  both: { label: t("两类均查到"), test: (j) => !!j.sponsor_h1b && !!j.sponsor_perm },
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
  const time = `${d.getMonth() + 1}/${d.getDate()}`;
  return `${time} · ${RUN_STATUS[r.status].text}${r.counts.kept != null ? ` · ${t("保留 {n}", { n: r.target_jobs ? `${r.counts.kept} / ${r.target_jobs}` : r.counts.kept })}` : ""}`;
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
  const [pasted, setPasted] = useState<JobSummary[]>([]); // 自己贴上的职位，每个视图都排在最上面
  const [removed, setRemoved] = useState<Set<string>>(new Set()); // 永久删除的
  const [statusOf, setStatusOf] = useState<Record<string, ApplicationStatus | null>>({}); // 这页里改过的投递状态
  const [sponsor, setSponsor] = useState(true);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [bucket, setBucket] = useState<Bucket>("kept");
  // 「这次只找到 N 个」的提示：按 ✕ 后这个批次不再显示（记在浏览器里），新批次不够数时会再出现
  const [shortHidden, setShortHidden] = useState<string | null>(() => {
    try {
      return localStorage.getItem(SHORT_NOTICE_KEY);
    } catch {
      return null;
    }
  });
  const hideShort = (id: string) => {
    setShortHidden(id);
    try {
      localStorage.setItem(SHORT_NOTICE_KEY, id);
    } catch {
      // 无痕模式等存不了：只在这次页面里隐藏
    }
  };
  const [visaFilter, setVisaFilter] = useState<VisaFilter>("all");
  const [sort, setSort] = useState<"place" | "score">("place");
  const [query, setQuery] = useState("");
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

  const loadPasted = useCallback(() => api.get<JobSummary[]>("/api/jobs?pasted=true").then(setPasted), []);

  useEffect(() => {
    Promise.all([
      loadSites(),
      loadRuns(),
      loadPasted(),
      api.get<SearchSource>("/api/search/source").then(setSource),
      api.get<{ data: JobPreferences }>("/api/preferences").then((p) => setPrefs(p.data)),
    ]).catch((e) => setError(e.message));
    api.get<Coverage>("/api/sponsor/coverage").then(setCoverage).catch(() => undefined);
  }, [loadSites, loadRuns, loadPasted]);

  // 签证资料导入中：每 5 秒更新进度；导入完成时重新读取职位，签证历史就会补上
  const importing = coverage?.import?.state === "running";
  useEffect(() => {
    if (!importing) return;
    const timer = setInterval(() => {
      api
        .get<Coverage>("/api/sponsor/coverage")
        .then((c) => {
          setCoverage(c);
          if (c.import?.state === "done") {
            setNotice(t("签证资料导入完成，职位的 H-1B / 绿卡已更新。"));
            (view === ALL_SAVED ? loadSaved() : loadRun()).catch(() => undefined);
          }
        })
        .catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
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
    // 拉黑写进了求职需求；不重读的话，下次保存 tag 或目标数会用旧资料盖掉它
    api.get<{ data: JobPreferences }>("/api/preferences").then((p) => setPrefs(p.data)).catch(() => undefined);
    (view === ALL_SAVED ? loadSaved() : loadRun()).catch((e) => setError(e.message));
    loadPasted().catch(() => undefined);
  };

  const active = run?.status === "pending" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void loadRun().catch(() => undefined), 3000);
    return () => clearInterval(timer);
  }, [active, loadRun]);

  // 跑完时更新批次清单
  useEffect(() => {
    if (run && !active) void loadRuns().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  const updateSite = async (id: string, patch: Partial<Pick<JobSite, "enabled" | "max_results" | "access_method">>) => {
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

  // 目标可投职位数：直接保存到求职需求
  const saveTarget = async (target_jobs: number) => {
    if (!prefs || target_jobs === prefs.search.target_jobs) return;
    setError("");
    try {
      const r = await api.put<{ data: JobPreferences }>("/api/preferences", { ...prefs, search: { ...prefs.search, target_jobs } });
      setPrefs(r.data);
    } catch (e) {
      setError((e as Error).message);
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

  // manual = 不认识的网址（多半是公司自己的招聘页）
  const siteName = (id: string) => (id === "manual" ? t("其他网站") : t(sites.find((s) => s.id === id)?.name ?? id));
  const chosen = sites.filter((s) => s.enabled && s.access_method !== "paste_only");
  const target = prefs?.search.target_jobs ?? 20;
  const busy = (runs ?? []).some((r) => r.status === "pending" || r.status === "running");
  const boardCount = sites.reduce((n, s) => n + (s.access_method === "ats_api" ? s.boards : 0), 0);

  const pastedIds = useMemo(() => new Set(pasted.map((j) => j.id)), [pasted]);
  const all = useMemo<JobRow[]>(() => {
    const base: JobRow[] = view === ALL_SAVED ? (saved ?? []) : (run?.jobs ?? []);
    const list = [...pasted, ...base.filter((j) => !pastedIds.has(j.id))];
    const q = query.trim().toLowerCase();
    return list
      .filter((j) => !removed.has(j.id) && (!q || [j.title, j.company.display_name, j.location_text].join(" ").toLowerCase().includes(q)))
      .map((j) => (j.id in statusOf ? { ...j, application_status: statusOf[j.id] } : j));
  }, [view, saved, run, pasted, pastedIds, removed, statusOf, query]);

  const visible = useMemo(() => {
    const list = all.filter(
      (j) =>
        inBucket(j, bucket) &&
        VISA_FILTER[visaFilter].test(j),
    );
    // 已投递按投递时间、已删除按删除时间，新的在上面
    const when = (j: JobRow) => Date.parse((bucket === "applied" ? j.applied_at : j.status_at) ?? j.status_at ?? "") || 0;
    const sorted =
      sort === "score"
        ? [...list].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
        : timeSorted
          ? [...list].sort((a, b) => when(b) - when(a))
          : list;
    return [...sorted.filter((j) => pastedIds.has(j.id)), ...sorted.filter((j) => !pastedIds.has(j.id))];
  }, [all, bucket, visaFilter, sort, timeSorted, pastedIds]);

  const count = (b: Bucket) => all.filter((j) => inBucket(j, b)).length;
  const paused = new Set(prefs?.paused_roles ?? []);
  const roles = (prefs?.target_roles ?? []).filter((r) => !paused.has(r)); // 启用中的职位
  const p = run?.progress;
  const pct = p && p.total ? Math.round((p.done / p.total) * 100) : 0;
  const searching = active && (p?.phase === "searching" || !p?.total);
  const bad = run ? run.sites.filter((s) => s.status === "blocked" || s.status === "failed").length : 0;
  const sourceSummary = active
    ? p?.phase === "searching"
      ? t("正在各网站搜索…")
      : t("{ok} 个正常 · {bad} 个有问题", { ok: run!.sites.length - bad, bad })
    : t("{n} 个来源 · 目标 {target} 个可投", { n: chosen.length, target });

  return (
    <div className="stack">
      {error && <p className="error">{error}</p>}
      {notice && (
        <p className="notice row between">
          <span>{notice}</span>
          <button type="button" className="link" onClick={() => setNotice("")}>
            {t("知道了")}
          </button>
        </p>
      )}
      {source && !source.ready && (
        <p className="error">
          {t("搜索来源：{label}", { label: source.label })} · <Link to="/settings">{t("到模型连接处理")}</Link> {t("（Greenhouse / Lever / Ashby 不需要搜索来源，仍可搜索）")}
        </p>
      )}
      {coverage && <ImportBanner coverage={coverage} />}
      {coverage && coverage.dataset_count === 0 && !coverage.import && (
        <p className="notice">
          {t("尚未导入官方签证资料，签证历史会显示「未查」。导入方式见 README 的「签证资料」一节")} (<code>scripts/sponsor_data/</code>).
        </p>
      )}

      <section className="search-row" aria-label={t("搜索条件")} ref={pop.ref}>
        <Paper stock="graph" tilt={false} className="search-cells">
          <div className="pop-wrap">
            <button type="button" className="cell" aria-expanded={pop.open === "roles"} onClick={() => pop.toggle("roles")}>
              <span className="cell-label">{t("目标职位 ▾")}</span>
              <span className="cell-value one-line">
                {roles.length ? roles[0] : t("未启用任何职位")}
                {roles.length > 1 && <span className="muted"> +{roles.length - 1}</span>}
                {paused.size > 0 && <span className="muted small"> · {t("{n} 个停用", { n: paused.size })}</span>}
              </span>
            </button>
            {pop.open === "roles" && prefs && (
              <div className="pop">
                <div className="row between">
                  <b>{t("目标职位")}</b>
                  <span className="muted small">{savingRoles ? <><Spinner /> {t("保存中")}</> : t("改动会直接保存")}</span>
                </div>
                <RoleTags roles={prefs.target_roles} paused={prefs.paused_roles} onChange={saveRoles} />
                <div className="muted small">{t("点 tag 切换启用 / 停用；停用的不会拿去搜索和评分。其他条件到")} <Link to="/preferences">{t("求职需求")}</Link> {t("修改。")}</div>
              </div>
            )}
          </div>
          <Link to="/preferences" className="cell">
            <span className="cell-label">{t("地点顺序")}</span>
            <span className="cell-value">{prefs?.locations.filter(Boolean).join(" → ") || t("未填写")}</span>
          </Link>
          <div className="pop-wrap">
            <button type="button" className="cell" aria-expanded={pop.open === "sources"} onClick={() => pop.toggle("sources")}>
              <span className="cell-label">{t("来源 ▾")}</span>
              <span className="cell-value">{sourceSummary}</span>
            </button>
            {pop.open === "sources" && <SourcesPanel sites={sites} run={active ? run : null} boardCount={boardCount} target={target} onTarget={saveTarget} onUpdate={updateSite} onBoardsChanged={loadSites} />}
          </div>
          <label className="cell">
            <Checkbox checked={sponsor} onCheckedChange={(v) => setSponsor(v === true)} />
            <span>
              <span className="cell-label">{t("签证历史")}</span>
              <span className="cell-value">{t("同时查 H-1B / 绿卡")}</span>
            </span>
          </label>
        </Paper>

        {active ? (
          <Button type="button" variant="outline" size="lg" className="search-btn" onClick={cancel}>
            {p?.phase === "searching" ? t("搜索中") : `${p?.done ?? 0} / ${p?.total ?? 0}`} · {t("取消")}
          </Button>
        ) : (
          <Button type="button" size="lg" className="search-btn" onClick={start} disabled={starting || busy || chosen.length === 0}>
            {busy ? <><Spinner />{t("搜索进行中…")}</> : starting ? <><Spinner />{t("正在建立批次…")}</> : <><Icon name="search" size={20} />{t("搜索")}</>}
          </Button>
        )}

        <div className="pop-wrap">
          <Button type="button" variant="outline" size="lg" className="search-btn" aria-expanded={pop.open === "paste"} onClick={() => pop.toggle("paste")}>
            {t("贴职位")}
          </Button>
          {pop.open === "paste" && (
            <div className="pop right">
              <PasteJob />
            </div>
          )}
        </div>
      </section>

      <section className="filter-row" aria-label={t("结果筛选")}>
        <div className="row">
          <NativeSelect aria-label={t("搜索批次")} value={view ?? ""} onChange={(e) => setView(e.target.value)} style={{ maxWidth: "100%" }}>
            {(runs ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {runLabel(r)}
              </option>
            ))}
            <option value={ALL_SAVED}>{t("所有已存的职位")}</option>
          </NativeSelect>
          <Seg<Bucket>
            label={t("职位分组")}
            value={bucket}
            onChange={setBucket}
            options={[
              { value: "kept", label: t("待看 {n}", { n: count("kept") }) },
              { value: "applied", label: t("已投递 {n}", { n: count("applied") }) },
              { value: "deleted", label: t("已删除 {n}", { n: count("deleted") }) },
            ]}
          />
          <Input type="search" className="w-56" aria-label={t("搜索职位")} placeholder={t("搜索职称、公司或地点")} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="row">
          <NativeSelect aria-label={t("签证筛选")} value={visaFilter} onChange={(e) => setVisaFilter(e.target.value as VisaFilter)}>
            {(Object.keys(VISA_FILTER) as VisaFilter[]).map((k) => (
              <option key={k} value={k}>
                {VISA_FILTER[k].label}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect aria-label={t("排序")} value={sort} onChange={(e) => setSort(e.target.value as "place" | "score")}>
            <option value="place">{bucket === "applied" ? t("排序：最近投递") : bucket === "deleted" ? t("排序：最近删除") : t("排序：地点优先")}</option>
            <option value="score">{t("排序：匹配分数")}</option>
          </NativeSelect>
        </div>
      </section>

      {run?.error && <p className="error">{run.error}</p>}
      {run?.status === "completed" && run.target_jobs != null && (run.counts.kept ?? 0) < run.target_jobs && shortHidden !== run.id && (
        <p className="notice row between" style={{ flexWrap: "nowrap" }}>
          <span>
            {t("这次只找到 {kept} 个可投职位（目标 {target} 个）：各网站能找到的职位都检查完了。可以多勾几个来源，或放宽求职条件后再搜一次。", {
              kept: run.counts.kept ?? 0,
              target: run.target_jobs,
            })}
          </span>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={t("关闭提示")} title={t("关闭提示")} onClick={() => hideShort(run.id)}>
            <Icon name="x" />
          </Button>
        </p>
      )}

      <section className="stack" aria-label={t("职位列表")}>
        {visible.map((j) => (
          <JobCard
            key={j.id}
            job={j}
            siteName={siteName}
            onStatus={(st) => setStatusOf((m) => ({ ...m, [j.id]: st }))}
            onRemoved={() => setRemoved((s) => new Set(s).add(j.id))}
            onBlacklisted={reloadJobs}
          />
        ))}
        {(runs === null || (view === ALL_SAVED && saved === null) || (runId && run === null)) && !error && <Loading className="card" text={t("读取职位中…")} />}
        {runs && !(view === ALL_SAVED && saved === null) && !(runId && run === null) && visible.length === 0 && !active && (
          <div className="card muted">{bucket === "deleted" ? t("没有已删除的职位。") : bucket === "applied" ? t("还没有标记为已投递的职位。投完后按职位卡上的「我已投递」。") : t("没有符合筛选条件的职位。")}</div>
        )}
        {active && (
          <div className="card search-progress">
            {p?.note && <p className="notice">{p.note}</p>}
            <div className="loading-line muted">
              <Spinner size={18} />
              <span>
                {searching ? t("正在各网站搜索职位…") : t("正在读取、评分职位…")}
                {visible.length === 0 ? t("处理好的职位会显示在这里。") : t("处理好的职位会陆续加进来。")} {t("可以离开这个页面，搜索会继续。")}
              </span>
            </div>
            <div className="progress-row">
              <div
                className={`progress${searching ? " indeterminate" : ""}`}
                role="progressbar"
                aria-label={t("搜索进度")}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={searching ? undefined : pct}
              >
                <span style={searching ? undefined : { width: `${Math.max(pct, 2)}%` }} />
              </div>
              <b className="progress-pct">{searching ? "—" : `${pct}%`}</b>
            </div>
            <div className="muted small">{searching ? t("还在找职位网址，找完才知道总数") : t("已找到 {done} / {total} 个可投职位 · 已检查 {checked} 个", { done: p?.done ?? 0, total: p?.total ?? 0, checked: p?.checked ?? 0 })}</div>
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
  target,
  onTarget,
  onUpdate,
  onBoardsChanged,
}: {
  sites: JobSite[];
  run: SearchRunDetail | null;
  boardCount: number;
  target: number;
  onTarget: (n: number) => void;
  onUpdate: (id: string, patch: Partial<Pick<JobSite, "enabled" | "max_results" | "access_method">>) => void;
  onBoardsChanged: () => void;
}) {
  const [boards, setBoards] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // 登录浏览器有没有在设定页开启：没开时 LinkedIn 只能用网页搜索
  const [browserOn, setBrowserOn] = useState(false);
  useEffect(() => {
    if (!DEMO) api.get<BrowserStatus>("/api/browser").then((b) => setBrowserOn(b.enabled)).catch(() => undefined);
  }, []);
  if (boards) {
    return (
      <div className="pop">
        <AtsBoards onChange={onBoardsChanged} />
        <div>
          <button type="button" className="link" onClick={() => setBoards(false)}>
            {t("← 返回来源")}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="pop">
      <label className="inline">
        <span style={{ flex: 1 }}>
          <b>{t("目标可投职位数")}</b>
          <span className="muted small" style={{ display: "block" }}>
            {t("找到这么多个可投的职位就停；被排除、之前已有的不算。")}
          </span>
        </span>
        <input
          aria-label={t("目标可投职位数")}
          type="number"
          min={1}
          max={200}
          defaultValue={target}
          onChange={(e) => {
            // 不用 onBlur：点外面时弹窗先关掉，blur 不会触发
            const n = Number(e.target.value);
            clearTimeout(saveTimer.current);
            if (Number.isInteger(n) && n >= 1 && n <= 200) saveTimer.current = setTimeout(() => onTarget(n), 300);
          }}
          style={{ width: 80 }}
        />
      </label>
      <div>
        {sites.map((s) => {
          const live = run?.sites.find((x) => x.site_id === s.id);
          const pasteOnly = s.access_method === "paste_only";
          return (
            <div className="site-row" key={s.id}>
              <label className="inline">
                <input type="checkbox" checked={s.enabled} disabled={pasteOnly} onChange={(e) => onUpdate(s.id, { enabled: e.target.checked })} />
                <span>
                  <b>{t(s.name)}</b>
                  <span className="muted small" style={{ display: "block" }}>
                    {live ? (
                      <>
                        {RUN_SITE_STATUS[live.status].text} · {t("找到 {n}", { n: live.found_count })}
                        {live.message && <> · {linkify(live.message)}</>}
                      </>
                    ) : pasteOnly ? (
                      t("只支援贴网址 / JD")
                    ) : s.access_method === "ats_api" ? (
                      t("搜索找公司，再读官方 API · 已知 {n} 个公司 board", { n: s.boards })
                    ) : s.access_method === "browser" ? (
                      t("登录浏览器 · 用你的登录身份读职位")
                    ) : (
                      `${t("网页搜索 · 只读公开职位页")}${s.limitation_note ? ` · ${t(s.limitation_note)}` : ""}`
                    )}
                  </span>
                </span>
              </label>
              {BROWSER_SITES.includes(s.id) && (
                <span className="inline" style={{ flexShrink: 0, whiteSpace: "nowrap" }}>
                  <NativeSelect size="sm" aria-label={t("{name} 的取得方式", { name: s.name })} value={s.access_method} onChange={(e) => onUpdate(s.id, { access_method: e.target.value as JobSite["access_method"] })}>
                    <option value="web_search">{t("网页搜索")}</option>
                    <option value="browser" disabled={!browserOn}>
                      {t("登录浏览器")}
                    </option>
                  </NativeSelect>
                  {!browserOn && (
                    <Link className="small" to="/settings">
                      {t("到设定开启")}
                    </Link>
                  )}
                </span>
              )}
              {!pasteOnly && (
                <label className="inline" title={t("每一轮最多从这个网站拿几个职位页")}>
                  {t("上限")}
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
        <span className="muted">{t("每个职位约 20–40 秒")}</span>
        <button type="button" className="link" onClick={() => setBoards(true)}>
          {t("管理公司 board（{n}）", { n: boardCount })}
        </button>
      </div>
      <div className="muted small">{t("只读取公开页面；遇到登录、CAPTCHA 或验证页就停下并记录原因，不绕过。本工具不会代你投递或联系雇主。")}</div>
    </div>
  );
}

// 能改用登录浏览器的网站（后端的 BROWSER_SITES）
const BROWSER_SITES = ["linkedin"];

// 旧的 badge 类别对应 looseleaf Badge：pass 绿、warn 橙、fail 粉，其余只描边
function tagProps(cls: string): { variant?: "outline"; tone?: "grass" | "tangerine" | "bubblegum" } {
  return cls === "pass" ? { tone: "grass" } : cls === "warn" ? { tone: "tangerine" } : cls === "fail" ? { tone: "bubblegum" } : { variant: "outline" };
}

function JobCard({
  job,
  siteName,
  onStatus,
  onRemoved,
  onBlacklisted,
}: {
  job: JobRow;
  siteName: (id: string) => string;
  onStatus: (s: ApplicationStatus | null) => void;
  onRemoved: () => void;
  onBlacklisted: (message: string) => void;
}) {
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

  const loadDetail = () => detail || api.get<JobDetail>(`/api/jobs/${job.id}`).then(setDetail).catch((e) => setError(e.message));
  const toggle = () => {
    setOpen(!open);
    if (!open) loadDetail();
  };

  // 「材料与内推」窗口：三个 tab 都留着不卸载，切换或关掉再开，写到一半的内容还在
  const [win, setWin] = useState(false);
  const [tab, setTab] = useState<MaterialKind | "reach_out">("cover_letter");
  const [material, setMaterial] = useState<MaterialKind>("cover_letter");
  const [reached, setReached] = useState(false);
  const sent = useRef(false);
  const pickTab = (next: MaterialKind | "reach_out") => {
    setTab(next);
    if (next === "reach_out") setReached(true);
    else setMaterial(next);
  };
  const openWin = () => {
    setWin(true);
    loadDetail(); // 要知道有没有存 JD
  };
  // 记录发送后状态会变成「已请求内推」、卡片会移到别的分组：等窗口关了再更新，免得窗口用到一半消失
  const closeWin = () => {
    setWin(false);
    if (!sent.current) return;
    sent.current = false;
    api
      .get<{ status: ApplicationStatus; applied_at: string | null } | null>(`/api/jobs/${job.id}/application`)
      .then((a) => {
        if (!a) return;
        setAppliedAt(a.applied_at);
        changed(a.status);
      })
      .catch((e) => setError(e.message));
  };
  const winTitle = `${job.title} · ${job.company.display_name}`;

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
  const rec = job.recommendation ? REC_TAG[job.recommendation] : excluded ? { text: t("已排除"), cls: "fail" } : { text: t("未评分"), cls: "" };
  const policy = POLICY_TAG[job.sponsorship_policy];
  const visa = job.sponsor_status ? SPONSOR_STATUS[job.sponsor_status] : null;
  const posted = job.posted_text || (job.posted_at ? t("发布于 {date}", { date: new Date(job.posted_at).toLocaleDateString(locale) }) : t("发布时间未知"));
  const note =
    run && run.exclusion_reasons.length > 0
      ? t("排除原因：{list}", { list: run.exclusion_reasons.map((r) => t(r.label)).join(t("；")) })
      : run?.outcome === "duplicate"
        ? t("在之前的搜索批次里已经出现过。")
        : null;
  const employment = job.employment_type !== "unknown" ? EMPLOYMENT[job.employment_type] : null;
  // 仍在招聘就不写；只提示没核实或已下架
  const verified = job.status === "unverified" ? t("未在官网核实是否仍在招聘") : job.status === "expired" ? t("已下架 / 过期") : null;
  const sourceLine = `${job.company.display_name} · ${job.found_on.length ? t("来源：{sites}", { sites: job.found_on.map(siteName).join("、") }) : t("自己加入的职位")}`;
  const m = detail?.match;

  return (
    <Card stock="paper" className={`job-card gap-0 py-0${isSubmitted(status) ? " submitted" : ""}`}>
      <div className="job-main">
        <div className="job-info">
          <div className="muted">{sourceLine}</div>
          <h2 className="job-title">
            <Link to={`/jobs/${job.id}`}>{job.title}</Link>
          </h2>
          <div className="job-tags">
            {isSubmitted(status) && (
              <Badge tone={status === "rejected" ? "bubblegum" : status === "ghosted" ? "tangerine" : "marker"}>
                ✓ {APP_STATUS[status!].text}
                {appliedAt && ` · ${new Date(appliedAt).toLocaleDateString(undefined, { month: "numeric", day: "numeric" })}${status === "applied" || status === "referred" ? "" : t(" 投递")}`}
              </Badge>
            )}
            <Badge {...tagProps(rec.cls)}>{rec.text}</Badge>
            <Badge {...tagProps(policy.cls)}>Sponsorship：{policy.text}</Badge>
            {visa && (job.sponsor_status === "records_found" || job.sponsor_status === "no_match_in_scope") ? (
              <>
                <Badge {...tagProps(job.sponsor_h1b ? "pass" : "")}>{job.sponsor_h1b ? "✓" : "✗"} H-1B</Badge>
                <Badge {...tagProps(job.sponsor_perm ? "pass" : "")}>{job.sponsor_perm ? "✓" : "✗"} {t("绿卡 PERM")}</Badge>
              </>
            ) : (
              visa && <Badge {...tagProps(visa.cls)}>{t("H-1B / 绿卡：{text}", { text: visa.text })}</Badge>
            )}
          </div>
          <div>
            {show(job.location_text)} · {WORK_MODE[job.work_mode]}
            {employment && ` · ${employment}`} · <b style={{ fontWeight: 600 }}>{salary(job.salary_min, job.salary_max, job.salary_period)}</b> · {posted}
          </div>
          {note && (
            <div className="muted" style={{ marginTop: 2, color: excluded ? "var(--fail)" : undefined }}>
              {note}
            </div>
          )}
        </div>
        <div className="job-score">
          {job.score != null ? (
            <Stamp shape="round" text={String(job.score)} sub="/ 100" size={78} seed={job.id} label={`${job.score} / 100`} />
          ) : (
            <b>{t("未评分")}</b>
          )}
          <span className="muted small">{job.score != null ? t("匹配度估计") : excluded ? t("已排除") : t("尚未评分")}</span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      <div className="job-foot">
        <div className="row">
          <Button type="button" variant="link" size="sm" className="px-0" aria-expanded={open} onClick={toggle}>
            {open ? "▼" : "▶"} {t("匹配理由、风险和签证历史")}
          </Button>
          {verified && <span className="muted">{verified}</span>}
        </div>
        <div className="job-actions">
          {job.apply_url && (
            <Button asChild variant="outline" size="sm" className="text-link">
              <a href={job.apply_url} target="_blank" rel="noopener noreferrer">
                {t("打开职位 / 自行申请 ↗")}
              </a>
            </Button>
          )}
          {!deleted && (status === null || status === "saved") && (
            <Button type="button" variant="outline" size="sm" onClick={markApplied}>
              {t("我已投递")}
            </Button>
          )}
          <Button type="button" variant="outline" size="sm" onClick={openWin} title={t("Cover Letter、申请问答、找人内推")}>
            {t("材料与内推")}
          </Button>
          {deleted ? (
            <>
              <Button type="button" variant="outline" size="sm" onClick={restore}>
                {t("还原")}
              </Button>
              <ConfirmButton className="danger" message={t("永久删除「{title}」？评分、来源、投递记录都会一起删除，无法复原。", { title: job.title })} confirmLabel={t("确定永久删除")} onConfirm={purge}>
                {t("永久删除")}
              </ConfirmButton>
            </>
          ) : (
            <>
              <StatusSelect jobId={job.id} status={status} onChange={changed} />
              <BlockButton job={job} onDone={onBlacklisted} />
              {/* 不用确认：只是移到「已删除」，可以还原 */}
              <Button type="button" variant="outline" size="sm" className="text-destructive" onClick={dismiss}>
                {t("删除")}
              </Button>
            </>
          )}
        </div>
      </div>
      {open && !detail && !error && <Loading className="pad-x" />}
      {open && detail && (
        <div className="job-more">
          <div>
            <h3>{t("为什么匹配")}</h3>
            {!m && <p className="muted">{excluded ? t("这个职位已被排除，没有评分。") : t("尚未评分。")}</p>}
            {m && m.reasons.length === 0 && <p className="muted">{t("没有可以引用履历证据的理由。")}</p>}
            {/* 列表里只放理由；履历证据在职位详情页看 */}
            {m?.reasons.map((r, i) => (
              <div className="reason" key={i}>
                {r.text}
              </div>
            ))}
            <h3>{t("缺口与风险")}</h3>
            {(!m || m.gaps.length === 0) && <p className="muted">{t("无。")}</p>}
            {m?.gaps.map((g, i) => (
              <div className="reason" key={i}>
                <b style={{ color: g.severity === "high" ? "var(--fail)" : "var(--warn)", fontSize: 12 }}>{SEVERITY[g.severity]}</b> {g.text}
              </div>
            ))}
          </div>
          <div>
            {m && (
              <>
                {m.breakdown.role && <h3>{t("分项")}</h3>}
                {m.breakdown.role && (Object.keys(PART_LABEL) as (keyof typeof PART_LABEL)[]).map((k) => (
                  <div className="part" key={k} title={m.breakdown[k].reason}>
                    <div className="part-head">
                      <span>{PART_LABEL[k]}</span>
                      <span className="muted">
                        {m.breakdown[k].score} / {m.breakdown[k].max}
                      </span>
                    </div>
                    <Progress size="sm" value={m.breakdown[k].score} max={Math.max(m.breakdown[k].max, 1)} aria-label={PART_LABEL[k]} />
                  </div>
                ))}
                <p className="muted small">{t("分数是契合度估计，不是录取概率。")}</p>
              </>
            )}
            <h3>{t("公司签证历史")}</h3>
            {detail.sponsor ? (
              <>
                <div title={SPONSOR_STATUS[detail.sponsor.status].desc}>{SPONSOR_STATUS[detail.sponsor.status].text}</div>
                {/* 每类只写通过的件数和最近一年；逐年明细在职位详情页 */}
                {(["lca", "uscis_h1b", "perm"] as const)
                  // 全是 0 的年份不算记录
                  .map((prog) => [prog, (detail.sponsor!.summary.programs[prog] ?? []).filter((y) => y.filed || y.certified_or_approved || y.denied)] as const)
                  .filter(([, years]) => years.length)
                  .map(([prog, years]) => {
                    const approved = years.filter((y) => y.certified_or_approved > 0);
                    const n = approved.reduce((sum, y) => sum + y.certified_or_approved, 0);
                    const last = Math.max(...(approved.length ? approved : years).map((y) => y.fiscal_year));
                    return (
                      <div className="muted" key={prog} title={PROGRAM[prog]}>
                        {t("{program}：通过 {n} 件 · 最近 FY{year}", { program: PROGRAM_SHORT[prog], n: n.toLocaleString(locale), year: last })}
                      </div>
                    );
                  })}
              </>
            ) : (
              <div className="muted">{t("未查。")}</div>
            )}
            <Button asChild variant="link" size="sm" className="px-0">
              <Link to={`/jobs/${job.id}`}>{t("查看 JD 全文与完整记录")}</Link>
            </Button>
          </div>
        </div>
      )}

      <Modal open={win} title={winTitle} onClose={closeWin}>
        <Seg<MaterialKind | "reach_out">
          label={t("材料与内推")}
          value={deleted && tab === "reach_out" ? "cover_letter" : tab}
          onChange={pickTab}
          options={[
            { value: "cover_letter", label: "Cover Letter" },
            { value: "qa", label: t("申请问答") },
            ...(deleted ? [] : [{ value: "reach_out" as const, label: t("内推") }]),
          ]}
        />
        <div hidden={tab === "reach_out" && !deleted}>
          {detail ? <JobMaterials jobId={job.id} initialKind={material} hasJd={!!detail.jd_text} hideKinds /> : error ? <p className="error">{error}</p> : win && <Loading />}
        </div>
        {reached && !deleted && (
          <div hidden={tab !== "reach_out"}>
            <OutreachPanel job={job} onSent={() => (sent.current = true)} />
          </div>
        )}
      </Modal>

    </Card>
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
      const what = kind === "company" ? t("公司「{name}」", { name: job.company.display_name }) : t("职位「{name}」", { name: phrase.trim() });
      onDone(
        t("已把{what}加进黑名单，{n} 个相符的职位移到「已删除」", { what, n: r.dismissed }) +
          (r.kept_submitted ? t("；{n} 个已投递的保留", { n: r.kept_submitted }) : "") +
          t("。之后的搜索会排除它们。"),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pop-wrap" ref={pop.ref}>
      <Button type="button" variant="outline" size="sm" aria-expanded={pop.open === "block"} onClick={() => pop.toggle("block")}>
        {t("拉黑 ▾")}
      </Button>
      {pop.open === "block" && (
        <div className="pop right up">
          <b>{t("拉黑后不再看到")}</b>
          <label className="inline">
            <input type="radio" name={`block-${job.id}`} checked={kind === "company"} onChange={() => setKind("company")} />
            <span>
              {t("这家公司：")}<b>{job.company.display_name}</b>
              <span className="muted small" style={{ display: "block" }}>{t("这家公司的所有职位")}</span>
            </span>
          </label>
          <label className="inline">
            <input type="radio" name={`block-${job.id}`} checked={kind === "title"} onChange={() => setKind("title")} />
            <span style={{ flex: 1 }}>
              {t("类似职位")}
              <span className="muted small" style={{ display: "block" }}>{t("职称里含这组词的职位（任何公司）；可以删短，例如只留「Sales Engineer」")}</span>
            </span>
          </label>
          {kind === "title" && <input aria-label={t("要拉黑的职称关键词")} value={phrase} onChange={(e) => setPhrase(e.target.value)} />}
          <div className="muted small">{t("已存的相符职位会移到「已删除」（可还原，已投递的保留），之后搜索也会排除。黑名单可在「求职需求 → 黑名单」修改。")}</div>
          {error && <p className="error">{error}</p>}
          <div className="row">
            <button type="button" className="danger-solid" onClick={submit} disabled={busy || (kind === "title" && !phrase.trim())}>
              {busy ? (
                <>
                  <Spinner />
                  {t("拉黑中…")}
                </>
              ) : (
                t("确定拉黑")
              )}
            </button>
            <button type="button" onClick={() => pop.setOpen(null)}>
              {t("取消")}
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
      <div className="muted small">{t("搜索时找到的公司、读过的职位页里的链接都会自动加入，也可以手动加入。")}</div>
      <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("Greenhouse / Lever / Ashby 的公司 board 网址")} aria-label={t("公司 board 网址")} />
      <div className="row">
        <input style={{ flex: 1, minWidth: 0 }} value={company} onChange={(e) => setCompany(e.target.value)} placeholder={t("公司名称（选填）")} aria-label={t("公司名称")} />
        <button type="button" onClick={add} disabled={!url.trim()}>
          {t("加入")}
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
              {t("移除")}
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
      setBusy(jd.trim() ? t("正在抽取职位资料…") : t("正在读取网页并抽取职位资料…"));
      const r = await api.post<{ job: JobDetail; notes: string[] }>("/api/jobs/ingest", {
        url: url || null,
        jd_text: jd || null,
        company,
        title,
      });
      setBusy(t("正在计算匹配评分…"));
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
        {t("职位网址")}
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
      </label>
      <label>
        {t("或贴 JD 全文（有贴就优先使用）")}
        <textarea rows={6} value={jd} onChange={(e) => setJd(e.target.value)} />
      </label>
      <div className="row">
        <input style={{ flex: 1, minWidth: 0 }} value={company} onChange={(e) => setCompany(e.target.value)} placeholder={t("公司（JD 没写时必填）")} aria-label={t("公司")} />
        <input style={{ flex: 1, minWidth: 0 }} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("职称（选填）")} aria-label={t("职称")} />
      </div>
      <div className="muted small">{t("Handshake 等需要登录的网站请用这里。只读取公开网页；遇到登录或验证页会停止，请改贴 JD。")}</div>
      <button type="button" className="primary" onClick={submit} disabled={!!busy || (!url.trim() && !jd.trim())}>
        {busy ? <><Spinner />{busy}</> : t("抽取并评分")}
      </button>
      {error && <p className="error">{error}</p>}
    </>
  );
}
