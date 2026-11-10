import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, JobSummary } from "../api";
import { StatusSelect } from "./ApplicationControl";
import { APP_STATUS, RECOMMENDATION, SPONSOR_STATUS, WORK_MODE, show } from "./labels";
import { Loading, Seg, usePopover } from "./ui";

interface StatsData {
  totals: Record<string, number | null>;
  funnel: { stage: string; label: string; count: number }[];
  application_status: Record<string, number>;
  sponsorship_policy: Record<string, number>;
  sponsor_status: Record<string, number>;
  location_tier: Record<string, number>;
  work_mode: Record<string, number>;
  exclusions: { code: string; label: string; count: number }[];
  sources: { site: string; name: string; found: number; kept: number; applied: number; interviews: number }[];
  easy_apply: Record<string, number>;
  salary: Record<string, number>;
  score: Record<string, number>;
  recommendation: Record<string, number>;
  trend: Record<"day" | "week", { date: string; applied: number; interviewing: number; other: number }[]>;
  backlog: { saved_not_applied: number; applied_no_update: number; stale_days: number };
}

interface Options {
  companies: { id: string; name: string }[];
  sites: { id: string; name: string }[];
  runs: string[];
}

type FilterKey = "company" | "site" | "run" | "location_tier" | "work_mode" | "status" | "date_from" | "date_to";
type Filters = Partial<Record<FilterKey, string>>;
type Range = "7" | "30" | "all" | "custom";

interface Bar {
  key: string;
  label: string;
  count: number;
}
interface Dim {
  key: string;
  label: string;
  param: string;
  items: Bar[];
  note?: string;
  empty?: string;
}
interface Drill {
  title: string;
  dim: string;
  value: string;
}

const POLICY: Record<string, string> = { explicit_yes: "写明提供", unclear: "没写（不明）", explicit_no: "写明不提供" };
const SALARY_ORDER = ["< $80k", "$80k–100k", "$100k–130k", "$130k–160k", "$160k–200k", "≥ $200k", "unknown"];
const SCORE_ORDER = ["75–100", "55–74", "40–54", "0–39", "none"];

function qs(f: Filters, extra: Record<string, string> = {}) {
  const p = new URLSearchParams();
  Object.entries({ ...f, ...extra }).forEach(([k, v]) => v && p.set(k, v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

function bars(rec: Record<string, number>, label: (k: string) => string, order?: string[]): Bar[] {
  const keys = order ? order.filter((k) => k in rec) : Object.keys(rec);
  return keys.map((k) => ({ key: k, label: label(k), count: rec[k] }));
}

function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Stats() {
  const [filters, setFilters] = useState<Filters>({});
  const [range, setRange] = useState<Range>("all");
  const [data, setData] = useState<StatsData | null>(null);
  const [opts, setOpts] = useState<Options | null>(null);
  const [locations, setLocations] = useState<string[]>([]);
  const [unit, setUnit] = useState<"day" | "week">("week");
  const [table, setTable] = useState(false);
  const [dimKey, setDimKey] = useState("application_status");
  const [drill, setDrill] = useState<Drill | null>(null);
  const [error, setError] = useState("");
  const pop = usePopover<"more">();

  useEffect(() => {
    api.get<Options>("/api/stats/options").then(setOpts).catch(() => undefined);
    api
      .get<{ data: { locations: string[] } }>("/api/preferences")
      .then((p) => setLocations(p.data.locations))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setError("");
    api
      .get<StatsData>(`/api/stats${qs(filters)}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [filters]);

  const tierLabel = (k: string) => (k === "none" ? "不在你的地点清单" : `第 ${k} 优先${locations[Number(k) - 1] ? `（${locations[Number(k) - 1]}）` : ""}`);

  const setF = (k: FilterKey, v: string) => {
    setDrill(null);
    if (k === "date_from" || k === "date_to") setRange("custom");
    setFilters((f) => ({ ...f, [k]: v || undefined }));
  };
  const pickRange = (r: Range) => {
    setDrill(null);
    setRange(r);
    setFilters((f) => ({ ...f, date_from: r === "all" ? undefined : daysAgo(Number(r)), date_to: undefined }));
  };
  const clear = () => {
    setDrill(null);
    setRange("all");
    setFilters({});
  };

  const dims: Dim[] = data
    ? [
        { key: "application_status", label: "投递状态", param: "application_status", empty: "还没有标记任何状态", items: bars(data.application_status, (k) => (k === "none" ? "未标记" : APP_STATUS[k]?.text ?? k)) },
        { key: "sponsor_status", label: "签证历史", param: "sponsor_status", items: bars(data.sponsor_status, (k) => SPONSOR_STATUS[k]?.text ?? k) },
        { key: "sponsorship_policy", label: "Sponsorship", param: "sponsorship_policy", items: bars(data.sponsorship_policy, (k) => POLICY[k] ?? k, ["explicit_yes", "unclear", "explicit_no"]) },
        { key: "location_tier", label: "地点", param: "location_tier", items: bars(data.location_tier, tierLabel, [...locations.map((_, i) => String(i + 1)), "none"]) },
        { key: "work_mode", label: "工作方式", param: "work_mode", items: bars(data.work_mode, (k) => WORK_MODE[k] ?? k) },
        { key: "salary", label: "薪资", param: "salary", note: "按年薪上限统计，时薪 × 2080。", items: bars(data.salary, (k) => (k === "unknown" ? "未列出" : k), SALARY_ORDER) },
        { key: "score", label: "匹配分数", param: "score", note: "分数是契合度估计，不是录取概率。", items: bars(data.score, (k) => (k === "none" ? "未评分（含被排除）" : k), SCORE_ORDER) },
        { key: "recommendation", label: "建议", param: "recommendation", items: bars(data.recommendation, (k) => (k === "none" ? "未评分" : RECOMMENDATION[k]?.text ?? k), ["apply", "maybe", "skip", "none"]) },
        { key: "exclusion", label: "排除原因", param: "exclusion", empty: "没有被排除的职位", items: data.exclusions.map((x) => ({ key: x.code, label: x.label, count: x.count })) },
        { key: "easy_apply", label: "Easy Apply", param: "easy_apply", items: bars(data.easy_apply, (k) => ({ yes: "有", no: "没有", unknown: "未知" })[k] ?? k) },
      ]
    : [];
  const dim = dims.find((d) => d.key === dimKey);
  const firstBar = dim?.items.find((b) => b.count > 0);
  const shown: Drill | null = drill ?? (dim && firstBar ? { title: `${dim.label}：${firstBar.label}`, dim: dim.param, value: firstBar.key } : null);

  const hasFilter = Object.values(filters).some(Boolean);
  const maxFound = data ? Math.max(...data.funnel.map((f) => f.count), 1) : 1;
  const replyRate = data?.totals.reply_rate;

  return (
    <div className="stack">
      {error && <p className="error">{error}</p>}

      <section className="row" aria-label="统计筛选" ref={pop.ref} style={{ position: "relative", zIndex: 5 }}>
        <Seg<Range>
          label="时间范围"
          value={range}
          onChange={pickRange}
          options={[
            { value: "7", label: "7 天" },
            { value: "30", label: "30 天" },
            { value: "all", label: "全部" },
          ]}
        />
        <select value={filters.site ?? ""} onChange={(e) => setF("site", e.target.value)} aria-label="来源网站">
          <option value="">所有来源</option>
          {opts?.sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select value={filters.location_tier ?? ""} onChange={(e) => setF("location_tier", e.target.value)} aria-label="地点">
          <option value="">所有地点</option>
          {locations.map((_, i) => (
            <option key={i} value={String(i + 1)}>
              {tierLabel(String(i + 1))}
            </option>
          ))}
          <option value="none">不在你的地点清单</option>
        </select>
        <select value={filters.work_mode ?? ""} onChange={(e) => setF("work_mode", e.target.value)} aria-label="工作方式">
          <option value="">所有工作方式</option>
          {Object.entries(WORK_MODE).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={filters.status ?? ""} onChange={(e) => setF("status", e.target.value)} aria-label="投递状态">
          <option value="">所有状态</option>
          <option value="none">未标记</option>
          {Object.entries(APP_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.text}
            </option>
          ))}
        </select>
        <div className="pop-wrap">
          <button type="button" aria-expanded={pop.open === "more"} onClick={() => pop.toggle("more")}>
            更多 ▾
          </button>
          {pop.open === "more" && (
            <div className="pop" style={{ width: 340 }}>
              <label>
                公司
                <select value={filters.company ?? ""} onChange={(e) => setF("company", e.target.value)}>
                  <option value="">所有公司</option>
                  {opts?.companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                搜索批次
                <select value={filters.run ?? ""} onChange={(e) => setF("run", e.target.value)}>
                  <option value="">所有批次</option>
                  {opts?.runs.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <div className="row">
                <label style={{ flex: 1, minWidth: 0 }}>
                  从
                  <input type="date" value={filters.date_from ?? ""} onChange={(e) => setF("date_from", e.target.value)} />
                </label>
                <label style={{ flex: 1, minWidth: 0 }}>
                  到
                  <input type="date" value={filters.date_to ?? ""} onChange={(e) => setF("date_to", e.target.value)} />
                </label>
              </div>
              <div className="muted small">日期是职位加入的日期。</div>
            </div>
          )}
        </div>
        {hasFilter && (
          <button type="button" className="link" onClick={clear}>
            清除筛选
          </button>
        )}
      </section>

      {!data && !error && <Loading className="card" />}
      {data && (
        <>
          <section className="card flush" aria-label="投递漏斗">
            <div className="funnel">
              {data.funnel.map((f, i) => {
                const prev = data.funnel[i - 1];
                const title = `漏斗：${f.label}`;
                return (
                  <button type="button" key={f.stage} className={`funnel-item${drill?.title === title ? " on" : ""}`} onClick={() => setDrill({ title, dim: "stage", value: f.stage })}>
                    <span className="muted">{f.label}</span>
                    <b>{f.count}</b>
                    <span className="funnel-track" style={{ display: "block" }}>
                      <span className="funnel-fill" style={{ width: `${Math.max(f.count ? 2 : 0, (f.count / maxFound) * 100)}%` }} />
                    </span>
                    <span className="muted small">{prev ? `占${prev.label} ${prev.count ? Math.round((f.count / prev.count) * 100) : 0}%` : "全部职位"}</span>
                  </button>
                );
              })}
              <div className="funnel-rate">
                <div className="muted">回复率</div>
                <div className="stat-big" style={{ color: "var(--accent-text)" }}>
                  {replyRate == null ? "—" : `${Math.round((replyRate as number) * 100)}%`}
                </div>
                <div className="muted small" style={{ marginTop: 14 }}>
                  面试、Offer、被拒 ÷ 已投递
                </div>
              </div>
            </div>
            <div className="backlog">
              <b>待处理</b>
              <button type="button" className="link" disabled={!data.backlog.saved_not_applied} onClick={() => setDrill({ title: "待处理：收藏了还没投", dim: "backlog", value: "saved_not_applied" })}>
                {data.backlog.saved_not_applied} 个收藏了还没投 →
              </button>
              <button type="button" className="link" disabled={!data.backlog.applied_no_update} onClick={() => setDrill({ title: `待处理：投递后 ${data.backlog.stale_days} 天没更新`, dim: "backlog", value: "applied_no_update" })}>
                {data.backlog.applied_no_update} 个投递超过 {data.backlog.stale_days} 天没更新 →
              </button>
              <button type="button" className="link" disabled={!data.totals.dismissed} onClick={() => setDrill({ title: "已删除的职位", dim: "application_status", value: "dismissed" })}>
                {data.totals.dismissed} 个已删除 →
              </button>
            </div>
          </section>

          <section className="card" aria-label="维度分析" style={{ paddingTop: 4 }}>
            <div className="tabs" role="tablist" aria-label="分析维度">
              {dims.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  role="tab"
                  aria-selected={d.key === dimKey}
                  className={d.key === dimKey ? "on" : ""}
                  onClick={() => {
                    setDimKey(d.key);
                    setDrill(null);
                  }}
                >
                  {d.label}
                </button>
              ))}
            </div>
            <div className="analysis">
              <div>
                {dim && dim.items.every((b) => b.count === 0) ? (
                  <p className="muted">{dim.empty ?? "还没有资料。"}</p>
                ) : (
                  dim && (
                    <BarList
                      items={dim.items}
                      activeKey={!drill || drill.dim === dim.param ? shown?.value : undefined}
                      onPick={(b) => setDrill({ title: `${dim.label}：${b.label}`, dim: dim.param, value: b.key })}
                    />
                  )
                )}
                {dim?.note && <p className="muted small" style={{ margin: 8 }}>{dim.note}</p>}
              </div>
              <div className="drill">{shown ? <DrillDown filters={filters} {...shown} /> : <p className="muted">点左边的长条查看对应的职位。</p>}</div>
            </div>
          </section>

          <div className="two-col">
            <section className="card" aria-label="投递趋势">
              <div className="row between" style={{ marginBottom: 8 }}>
                <h2 className="sub-title" style={{ margin: 0, fontSize: 16 }}>
                  投递趋势
                </h2>
                <div className="row">
                  <button type="button" className="link" onClick={() => setTable(!table)}>
                    {table ? "查看图表" : "查看表格"}
                  </button>
                  <Seg
                    label="趋势单位"
                    value={unit}
                    onChange={setUnit}
                    options={[
                      { value: "week", label: "每周" },
                      { value: "day", label: "每日" },
                    ]}
                  />
                </div>
              </div>
              <Trend points={data.trend[unit]} unit={unit} table={table} />
            </section>

            <section className="card" aria-label="来源效果">
              <h2 className="sub-title" style={{ fontSize: 16, lineHeight: "44px", margin: 0 }}>
                来源效果
              </h2>
              {data.sources.length === 0 ? (
                <p className="muted">还没有资料。</p>
              ) : (
                <div className="scroll-x">
                  <table>
                    <thead>
                      <tr>
                        <th>网站</th>
                        <th className="num">找到</th>
                        <th className="num">保留</th>
                        <th className="num">投递</th>
                        <th className="num">面试</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.sources.map((s) => (
                        <tr key={s.site} className="clickable" onClick={() => s.site !== "(无来源链接)" && setDrill({ title: `来源：${s.name}`, dim: "site", value: s.site })}>
                          <td>{s.name === "(无来源链接)" ? "手动贴的 JD（无网址）" : s.name}</td>
                          <td className="num">{s.found}</td>
                          <td className="num">{s.kept}</td>
                          <td className="num">{s.applied}</td>
                          <td className="num">{s.interviews}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

/** 横向长条：单一色相表示数量；数值直接标在旁边；滑过有提示，点击在旁边列出职位。 */
function BarList({ items, activeKey, onPick }: { items: Bar[]; activeKey?: string; onPick: (b: Bar) => void }) {
  const max = Math.max(...items.map((b) => b.count), 1);
  const total = items.reduce((n, b) => n + b.count, 0);
  return (
    <div>
      {items.map((b) => {
        const share = total ? `${Math.round((b.count / total) * 100)}%` : "";
        return (
          <button type="button" key={b.key} className={`barrow${activeKey === b.key ? " on" : ""}`} onClick={() => onPick(b)} disabled={b.count === 0} title={`${b.label}：${b.count}（${share}），点击查看职位`}>
            <span>{b.label}</span>
            <span className="bartrack">
              <span className="bar" style={{ width: `${(b.count / max) * 100}%` }} />
            </span>
            <span className="barvalue">
              {b.count} <span className="muted">{share}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Trend({ points, unit, table }: { points: { date: string; applied: number; interviewing: number; other: number }[]; unit: string; table: boolean }) {
  if (points.length === 0) return <p className="muted">还没有状态变更记录。在职位上标记「已投递」后会出现在这里。</p>;
  const max = Math.max(...points.map((p) => p.applied), 1);
  if (table)
    return (
      <div style={{ maxHeight: 200, overflow: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>{unit === "week" ? "周（起始日）" : "日期"}</th>
              <th className="num">投递</th>
              <th className="num">面试</th>
              <th className="num">其他</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.date}>
                <td>{p.date}</td>
                <td className="num">{p.applied}</td>
                <td className="num">{p.interviewing}</td>
                <td className="num">{p.other}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  return (
    <>
      <div className="trend" role="img" aria-label={`${unit === "week" ? "每周" : "每日"}投递数，最高 ${max}`}>
        {points.map((p) => (
          <div key={p.date} className="trendcol" title={`${p.date}${unit === "week" ? " 那一周" : ""}：投递 ${p.applied}、进入面试 ${p.interviewing}、其他状态变更 ${p.other}`}>
            {p.applied > 0 && points.length <= 31 && <span className="trendnum">{p.applied}</span>}
            <span className="trendbar" style={{ height: `${(p.applied / max) * 82}%` }} />
          </div>
        ))}
      </div>
      <div className="row between" style={{ marginTop: 4 }}>
        <span className="muted small">{points[0].date}</span>
        <span className="muted small">{points[points.length - 1].date}</span>
      </div>
    </>
  );
}

function DrillDown({ filters, title, dim, value }: { filters: Filters } & Drill) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const url = useMemo(() => `/api/stats/jobs${qs(filters, { dim, value })}`, [filters, dim, value]);
  useEffect(() => {
    setJobs(null);
    api.get<JobSummary[]>(url).then(setJobs).catch(() => setJobs([]));
  }, [url]);
  return (
    <>
      <h2 className="sub-title">
        {title}（{jobs?.length ?? "…"}）
      </h2>
      {!jobs && <Loading />}
      {jobs && jobs.length === 0 && <p className="muted">没有职位。</p>}
      <div style={{ maxHeight: 340, overflow: "auto" }}>
        {jobs?.map((j) => (
          <div className="drill-row" key={j.id}>
            <Link to={`/jobs/${j.id}`}>
              <b style={{ display: "block", fontWeight: 600 }}>{j.title}</b>
              <span className="muted">
                {j.company.display_name} · {show(j.location_text)}
              </span>
            </Link>
            <b style={{ fontVariantNumeric: "tabular-nums" }}>{j.score ?? "—"}</b>
            <StatusSelect jobId={j.id} status={j.application_status} />
          </div>
        ))}
      </div>
    </>
  );
}
